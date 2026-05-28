"""
Market Trace V6.0 — 启动入口
初始化消息总线、数据库、启动 5 Agent、启动 FastAPI
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

import numpy as np
import yaml
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, Query, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from core.log_filter import desensitize as log_filter

load_dotenv()

CONFIG_PATH = Path("config/settings.yaml")


def _resolve_env_vars(raw: str) -> str:
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
    import re
    raw = re.sub(r"\$\{[^}]+\}", "", raw)
    return raw


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        logger.error("配置文件不存在: {}", CONFIG_PATH.absolute())
        sys.exit(1)
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(_resolve_env_vars(raw))


CONFIG = load_config()

logger.remove()
log_cfg = CONFIG["logging"]
logger.add(
    Path("logs") / "market_trace_{time:YYYY-MM-DD}.log",
    rotation=log_cfg["rotation"],
    retention=log_cfg["retention"],
    level=log_cfg["level"],
    format=log_cfg["format"],
    encoding="utf-8",
    enqueue=True,
    filter=log_filter,
)
logger.add(sys.stdout, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
           colorize=True)

START_TIME = time.time()
bus = None
db = None
notifier = None
llm_chain = None
_agent_tasks: list[asyncio.Task] = []


def _build_llm_chain(cfg: dict):
    from core.circuit_breaker import CircuitBreaker
    from core.llm_factory import OpenAICompatibleLLM, RuleBasedAnalyzer, LLMFallbackChain

    cb_cfg = cfg.get("circuit_breaker", {})
    cb_kwargs = dict(
        failure_threshold=cb_cfg.get("failure_threshold", 3),
        recovery_timeout=cb_cfg.get("recovery_timeout", 60),
        half_open_max_requests=cb_cfg.get("half_open_max_requests", 2),
    )

    llm_cfg = cfg.get("llm", {})
    primary = OpenAICompatibleLLM(
        "deepseek", llm_cfg.get("primary", {}),
        CircuitBreaker(name="llm:deepseek", **cb_kwargs),
    )
    secondary = OpenAICompatibleLLM(
        "gemini", llm_cfg.get("secondary", {}),
        CircuitBreaker(name="llm:gemini", **cb_kwargs),
    )
    tertiary = OpenAICompatibleLLM(
        "minimax", llm_cfg.get("tertiary", {}),
        CircuitBreaker(name="llm:minimax", **cb_kwargs),
    )
    rule_based = RuleBasedAnalyzer(llm_cfg.get("fallback", {}))

    return LLMFallbackChain(primary, secondary, tertiary, rule_based)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bus, db, llm_chain, _agent_tasks, notifier

    from core.bus import MessageBus
    from core.notifier import get_notifier
    from db.database import Database

    redis_cfg = CONFIG["redis"]
    bus_instance = MessageBus(
        host=redis_cfg["host"], port=redis_cfg["port"], db=redis_cfg["db"],
        password=redis_cfg["password"], max_connections=redis_cfg["max_connections"],
        retry_interval=redis_cfg["retry_interval"],
    )
    try:
        await bus_instance.connect(max_retries=3)
        bus = bus_instance
        logger.info("Redis 已连接")
    except Exception:
        logger.warning("Redis 不可用，将以无 Redis 模式运行")
        bus = None

    db_cfg = CONFIG.get("database", {})
    db = Database(database_url=db_cfg.get("url", "sqlite+aiosqlite:///data/market_trace.db"))
    await db.init()
    logger.info("数据库已初始化")

    llm_chain = _build_llm_chain(CONFIG)
    logger.info("LLM 回退链已就绪: DeepSeek → Gemini → MiniMax → 纯规则")

    notifier = get_notifier()
    if notifier.enabled:
        logger.info("微信通知已启用")
    else:
        logger.info("微信通知未配置 (设置 WXPUSHER_TOKEN + WXPUSHER_UID)")

    _agent_tasks = _start_agents()
    logger.info("{} 个 Agent 已启动", len(_agent_tasks))

    yield

    logger.info("正在停止所有 Agent...")
    for task in _agent_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*_agent_tasks, return_exceptions=True)
    logger.info("所有 Agent 已停止")

    if db:
        await db.close()
    if bus:
        await bus.close()
    logger.info("系统已关闭")


def _start_agents() -> list[asyncio.Task]:
    from data_provider.akshare_impl import AkShareProvider
    from data_provider.tushare_impl import TushareProvider
    from core.memory import CaseMemory
    from agents.macro_agent import MacroAgent
    from agents.signal_agent import SignalAgent
    from agents.trace_agent import TraceAgent
    from agents.risk_agent import RiskAgent
    from agents.chief_analyst import ChiefAnalyst

    tasks: list[asyncio.Task] = []

    ak_provider = AkShareProvider(bus, CONFIG)

    tushare_cfg = [p for p in CONFIG.get("data_providers", []) if p.get("name") == "tushare" and p.get("enabled")]
    tushare_provider = None
    if tushare_cfg and tushare_cfg[0].get("token"):
        tushare_provider = TushareProvider(bus, CONFIG, token=tushare_cfg[0]["token"])
        logger.info("Tushare 数据源已启用")

    primary_provider = tushare_provider or ak_provider

    macro = MacroAgent(bus, CONFIG, data_provider=ak_provider)
    tasks.append(asyncio.create_task(macro.start(), name="macro-agent"))

    memory = CaseMemory(max_cases=10000)
    signal = SignalAgent(bus, CONFIG, memory=memory)
    tasks.append(asyncio.create_task(signal.start(), name="signal-agent"))

    trace = TraceAgent(bus, CONFIG)
    tasks.append(asyncio.create_task(trace.start(), name="trace-agent"))

    risk = RiskAgent(bus, CONFIG)
    tasks.append(asyncio.create_task(risk.start(), name="risk-agent"))

    chief = ChiefAnalyst(bus, CONFIG, llm_chain=llm_chain)
    tasks.append(asyncio.create_task(chief.start(), name="chief-agent"))

    return tasks


app = FastAPI(
    title="Market Trace V6.0",
    description="A/B 股量化分析系统 — 多 Agent 协作 + AI 决策",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    redis_ok = False
    db_ok = False
    if bus:
        try:
            redis_ok = await bus.health_check()
        except Exception:
            pass

    if db:
        try:
            from sqlalchemy import text
            async with db._session_factory() as session:
                await session.execute(text("SELECT 1"))
                db_ok = True
        except Exception:
            pass

    agents = {}
    if bus and redis_ok:
        try:
            agents = await bus.check_all_heartbeats(["macro", "signal", "trace", "risk", "chief"])
        except Exception:
            pass

    llm_status = {}
    llm_cfg = CONFIG.get("llm", {})
    for tier, key in [("primary", "primary"), ("secondary", "secondary"), ("tertiary", "tertiary")]:
        provider = llm_cfg.get(key, {})
        llm_status[key] = {
            "provider": provider.get("provider", "unknown"),
            "model": provider.get("model", "unknown"),
            "api_key_configured": bool(provider.get("api_key") and "your-" not in str(provider.get("api_key", ""))),
        }

    uptime = time.time() - START_TIME
    all_ok = redis_ok and db_ok

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "1.0.0",
        "uptime_seconds": round(uptime, 1),
        "redis": "connected" if redis_ok else "disconnected",
        "database": "connected" if db_ok else "disconnected",
        "agents": agents,
        "llm_chain": llm_status,
        "agents_running": len([t for t in _agent_tasks if not t.done()]),
    }


@app.get("/status")
async def status():
    response = {"version": "1.0.0", "uptime_seconds": round(time.time() - START_TIME, 1)}

    if db:
        try:
            stats = await db.get_decision_stats()
            response["decision_stats"] = stats
            latest = await db.get_latest_decision()
            if latest:
                response["latest_decision"] = {
                    "action": latest.action, "confidence": latest.confidence,
                    "reasoning": latest.reasoning[:200], "provider": latest.provider_label,
                    "timestamp": latest.timestamp.isoformat(),
                }
        except Exception as e:
            response["decision_stats"] = {"error": str(e)}

        try:
            response["case_stats"] = await db.get_case_statistics()
        except Exception:
            response["case_stats"] = {"error": "unavailable"}

    return response


@app.get("/reports/{agent_name}")
async def get_reports(agent_name: str, symbol: str = Query(None),
                      limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    valid = {"macro", "signal", "trace", "risk", "chief"}
    if agent_name not in valid:
        return JSONResponse({"error": f"无效 Agent: {agent_name}，可选: {sorted(valid)}"}, status_code=400)
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        reports = await db.get_reports(agent=agent_name, limit=limit, offset=offset)
        return {
            "agent": agent_name, "count": len(reports),
            "items": [{"report_id": r.report_id, "agent": r.agent, "symbol": r.symbol,
                        "summary": r.summary, "confidence": r.confidence, "status": r.status,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None, "data": r.data}
                      for r in reports],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/reports/{agent_name}/latest")
async def get_latest_report(agent_name: str, symbol: str = Query(None)):
    valid = {"macro", "signal", "trace", "risk", "chief"}
    if agent_name not in valid:
        return JSONResponse({"error": f"无效 Agent: {agent_name}"}, status_code=400)
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        r = await db.get_latest_report(agent_name, symbol=symbol)
        if not r:
            return JSONResponse({"error": f"Agent {agent_name} 无最新报告"}, status_code=404)
        return {"report_id": r.report_id, "agent": r.agent, "symbol": r.symbol,
                "summary": r.summary, "confidence": r.confidence, "status": r.status,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None, "data": r.data}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/decisions")
async def get_decisions(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        decisions = await db.get_decisions(limit=limit, offset=offset)
        stats = await db.get_decision_stats()
        return {"count": len(decisions), "stats": stats,
                "items": [{"decision_id": d.decision_id, "action": d.action, "confidence": d.confidence,
                            "reasoning": d.reasoning[:300], "evidence_sources": d.evidence_sources,
                            "risk_override": d.risk_override, "provider_label": d.provider_label,
                            "provider_status": d.provider_status,
                            "timestamp": d.timestamp.isoformat() if d.timestamp else None}
                          for d in decisions]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/decisions/{decision_id}")
async def get_decision(decision_id: str):
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        from sqlalchemy import select
        from db.models import DecisionModel
        async with db._session_factory() as session:
            q = select(DecisionModel).where(DecisionModel.decision_id == decision_id)
            result = await session.execute(q)
            d = result.scalar_one_or_none()
            if not d:
                return JSONResponse({"error": f"决策 {decision_id} 不存在"}, status_code=404)
            return {"decision_id": d.decision_id, "action": d.action, "confidence": d.confidence,
                    "reasoning": d.reasoning, "evidence_sources": d.evidence_sources,
                    "evidence_chain": d.evidence_chain, "risk_override": d.risk_override,
                    "provider_label": d.provider_label, "provider_status": d.provider_status,
                    "timestamp": d.timestamp.isoformat() if d.timestamp else None}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


STOCK_POOL = CONFIG.get("stock_pool", [
    "000001","600519","601318","600036","000858","300750","601012",
])


async def _analyze_single(symbol: str) -> dict:
    """核心分析逻辑：Tushare→AkShare→Redis缓存降级→算指标→调LLM"""
    cached = None
    provider_cfg = [p for p in CONFIG.get("data_providers", []) if p.get("enabled")]
    tushare_token = next((p.get("token") for p in provider_cfg if p.get("name") == "tushare" and p.get("token")), None)
    cache_key = f"market:raw:{symbol}"

    # 1) 优先拉取最新实时数据（Tushare）
    if tushare_token:
        try:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            from data_provider.tushare_impl import TushareProvider
            tp = TushareProvider(bus, CONFIG, token=tushare_token)
            klines = await tp.fetch_kline(symbol, start_date, datetime.now().strftime("%Y%m%d"))
            if klines:
                cached = [{"close": k.close, "open": k.open, "high": k.high, "low": k.low,
                           "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()}
                          for k in klines]
                if bus:
                    await bus.cache_set(cache_key, cached, ttl=3600)
        except Exception:
            pass

    # 2) Tushare 失败时尝试 AkShare
    if not cached:
        try:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            from data_provider.akshare_impl import AkShareProvider
            ap = AkShareProvider(bus, CONFIG)
            klines = await ap.fetch_kline(symbol, start_date, datetime.now().strftime("%Y%m%d"))
            if klines:
                cached = [{"close": k.close, "open": k.open, "high": k.high, "low": k.low,
                           "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()}
                          for k in klines]
                if bus:
                    await bus.cache_set(cache_key, cached, ttl=3600)
        except Exception:
            pass

    # 3) 实时数据源均失败时，降级到 Redis 缓存
    if not cached and bus:
        cached = await bus.cache_get(cache_key)

    # 4) 盘中实时报价修正：优先 Tushare realtime，回退 AkShare spot
    if cached and tushare_token:
        try:
            from data_provider.tushare_impl import TushareProvider
            tp = TushareProvider(bus, CONFIG, token=tushare_token)
            rt = await tp.fetch_realtime(symbol)
            if rt and rt.get("price"):
                live_price = float(rt["price"])
                logger.info("Tushare 实时价: {} = {} (前收: {})", symbol, live_price, rt.get("pre_close"))
                if live_price > 0 and abs(live_price - float(cached[-1]["close"])) > 0.001:
                    cached[-1] = {**cached[-1], "close": live_price, "high": max(float(cached[-1]["high"]), live_price), "low": min(float(cached[-1]["low"]), live_price)}
        except Exception as e:
            logger.warning("Tushare 实时报价失败 ({}): {}", symbol, e)

    if not cached or len(cached) < 5:
        raise HTTPException(400, f"股票 {symbol} 数据不足，至少需要5条K线")

    closes = np.array([float(r["close"]) for r in cached])
    highs = np.array([float(r["high"]) for r in cached])
    lows = np.array([float(r["low"]) for r in cached])
    volumes = np.array([float(r["volume"]) for r in cached])

    from agents.signal_agent import SignalAgent
    from agents.trace_agent import TraceAgent

    sig = SignalAgent(bus, CONFIG)
    ta = TraceAgent(bus, CONFIG)

    ma5 = round(float(SignalAgent._calc_ma(closes, 5)[-1]), 2) if len(closes) >= 5 else None
    ma10 = round(float(SignalAgent._calc_ma(closes, 10)[-1]), 2) if len(closes) >= 10 else None
    ma20 = round(float(SignalAgent._calc_ma(closes, 20)[-1]), 2) if len(closes) >= 20 else None

    rsi_vals = SignalAgent._calc_rsi(closes, 14)
    rsi = round(float(rsi_vals[-1]), 2) if rsi_vals is not None and len(rsi_vals) > 0 and not np.isnan(rsi_vals[-1]) else None

    macd_dict = sig._calc_macd(closes)
    macd = {}
    if macd_dict and len(macd_dict.get("hist", [])) > 0:
        macd = {
            "dif": round(float(macd_dict["dif"][-1]), 4) if not np.isnan(macd_dict["dif"][-1]) else None,
            "dea": round(float(macd_dict["dea"][-1]), 4) if not np.isnan(macd_dict["dea"][-1]) else None,
            "histogram": round(float(macd_dict["hist"][-1]), 4) if not np.isnan(macd_dict["hist"][-1]) else None,
        }

    price = closes[-1]
    prev = closes[-2] if len(closes) > 1 else price
    change_pct = round((price - prev) / prev * 100, 2) if prev else 0

    vol_ratio = round(float(volumes[-1] / np.mean(volumes[:-1])), 2) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0

    trace_signals = []
    ta._detect_volume_spike(volumes, closes, trace_signals)
    if len(closes) >= 5:
        ta._detect_price_volume_divergence(closes, volumes, trace_signals)

    macro_rai = 0.5
    if bus:
        mc = await bus.cache_get("market:macro")
        if mc and isinstance(mc, dict):
            macro_rai = mc.get("risk_appetite_index", 0.5)

    decision = None
    if llm_chain:
        try:
            from core.schema import AgentReport, AgentName, DecisionAction
            reports = {
                "macro": AgentReport(agent=AgentName.MACRO, summary=f"RAI={macro_rai:.2f}",
                    data={"risk_appetite_index": macro_rai}, confidence=abs(macro_rai - 0.5) * 2),
                "signal": AgentReport(agent=AgentName.SIGNAL, summary=f"价格{price}",
                    data={"indicators": {"rsi": rsi, "macd": macd}, "signals": []}, confidence=0.5),
                "trace": AgentReport(agent=AgentName.TRACE, summary="量价分析",
                    data={"signals": trace_signals, "direction": "neutral"}, confidence=0.5),
            }
            dec = await llm_chain.analyze(reports)
            decision = {
                "action": dec.action.value, "confidence": dec.confidence,
                "reasoning": dec.reasoning, "provider": dec.provider_label,
            }
        except Exception:
            pass

    latest_ts = cached[-1]["timestamp"] if cached else None
    return {
        "symbol": symbol, "price": float(price), "change_pct": change_pct,
        "indicators": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "macd": macd, "rsi": rsi, "vol_ratio": vol_ratio},
        "trace_signals": [{"type": s["type"], "direction": s["direction"], "strength": s.get("strength", 0)} for s in trace_signals],
        "macro_rai": macro_rai, "decision": decision,
        "data_timestamp": latest_ts, "data_source": "tushare" if tushare_token else "akshare",
    }


# ─────────────────────────────────────────────
# API Token 认证（可选，未配置 API_TOKEN 时跳过）
# ─────────────────────────────────────────────

_API_TOKEN = os.environ.get("API_TOKEN", "")


async def _verify_api_token(authorization: str = Header(None)):
    """简单 Bearer Token 认证，保护消耗资源的端点"""
    if not _API_TOKEN:
        return  # 未配置 token，跳过认证
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "缺少 Authorization: Bearer <token> 请求头")
    if authorization[7:] != _API_TOKEN:
        raise HTTPException(403, "API Token 无效")


@app.post("/analyze/{symbol}", dependencies=[Depends(_verify_api_token)])
async def analyze_stock(symbol: str):
    """诊股：拉数据→技术分析→AI决策"""
    try:
        result = await _analyze_single(symbol)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("诊股失败 {}: {}", symbol, e)
        return JSONResponse({"error": str(e), "symbol": symbol}, status_code=500)


STRATEGIES = {
    "breakout": (lambda c,h,v: (
        c[-1] > max(h[-20:-1]) and v[-1] > np.mean(v[-20:-1]) * 1.5 and len(c) >= 2 and c[-1] > c[-2]
    ), "强势突破"),
    "oversold": (lambda c,_,v: (
        len(c) >= 14 and _calc_rsi14(c) < 35 and (c[-1]-c[-5])/c[-5] < -0.03
    ), "超跌反弹"),
    "strength": (lambda c,_,v: (
        len(c) >= 5 and v[-1] > np.mean(v[-5:-1]) * 2 and c[-1] > c[-5]
    ), "主力介入"),
    "risk": (lambda c,h,_: (
        len(c) >= 14 and _calc_rsi14(c) > 70 and c[-1] < c[-20]
    ), "风险预警"),
    "ma_golden_cross": (lambda c,_,v: (
        len(c) >= 20 and _calc_ma_val(c, 5)[-1] > _calc_ma_val(c, 20)[-1]
        and _calc_ma_val(c, 5)[-2] <= _calc_ma_val(c, 20)[-2]
        and v[-1] > np.mean(v[-20:-1]) * 1.2
    ), "均线金叉"),
    "volume_breakout": (lambda c,_,v: (
        len(c) >= 5 and v[-1] > np.mean(v[-20:-1]) * 3
        and (c[-1] - c[-5]) / c[-5] > 0.05
    ), "放量突破"),
    "rsi_reversal": (lambda c,_,v: (
        len(c) >= 14 and _calc_rsi14(c) < 30
        and (_calc_rsi14(c) - _calc_rsi_val(c, 2)) > 3
    ), "RSI反转"),
}


def _calc_rsi14(closes):
    from agents.signal_agent import SignalAgent
    r = SignalAgent._calc_rsi(np.array(closes), 14)
    return float(r[-1]) if r is not None and len(r) > 0 else 50


def _calc_ma_val(closes, period):
    from agents.signal_agent import SignalAgent
    return SignalAgent._calc_ma(np.array(closes), period)


def _calc_rsi_val(closes, days_ago):
    from agents.signal_agent import SignalAgent
    r = SignalAgent._calc_rsi(np.array(closes), 14)
    if r is not None and len(r) > days_ago:
        return float(r[-days_ago - 1]) if len(r) > days_ago else float(r[0])
    return 50


@app.post("/screen/{strategy}", dependencies=[Depends(_verify_api_token)])
async def screen_stocks(strategy: str):
    """选股：按策略扫描股票池"""
    if strategy not in STRATEGIES:
        return JSONResponse({"error": f"策略不存在: {strategy}，可选: {list(STRATEGIES.keys())}"}, status_code=400)

    condition, strategy_name = STRATEGIES[strategy]
    results = []

    for symbol in STOCK_POOL:
        try:
            cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
            if not cached or len(cached) < 20:
                continue
            closes = [float(r["close"]) for r in cached]
            highs = [float(r["high"]) for r in cached]
            vols = [float(r["volume"]) for r in cached]
            if condition(closes, highs, vols):
                results.append({
                    "symbol": symbol, "price": closes[-1],
                    "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else 0,
                    "vol_ratio": round(vols[-1] / np.mean(vols[:-1]), 2) if len(vols) > 1 and np.mean(vols[:-1]) > 0 else 1,
                })
        except Exception:
            continue

    results.sort(key=lambda x: -x["vol_ratio"])
    return {"strategy": strategy_name, "matched": len(results), "results": results[:20]}


_DASHBOARD_TEMPLATE: str | None = None


def _get_dashboard_html() -> str:
    global _DASHBOARD_TEMPLATE
    if _DASHBOARD_TEMPLATE is None:
        template_path = Path("templates/dashboard.html")
        if not template_path.exists():
            return "<html><body><h1>模板文件未找到</h1></body></html>"
        _DASHBOARD_TEMPLATE = template_path.read_text(encoding="utf-8")
    return _DASHBOARD_TEMPLATE.replace("{{API_TOKEN}}", _API_TOKEN)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _get_dashboard_html()


def main():
    logger.info("Market Trace V6.0 正在启动...")
    logger.info("LLM: {}::{}", CONFIG["llm"]["primary"]["provider"], CONFIG["llm"]["primary"]["model"])
    logger.info("数据源: {}", [p["name"] for p in CONFIG["data_providers"] if p.get("enabled")])
    uvicorn.run("main:app", host="0.0.0.0", port=19377, log_config=None, access_log=False)


if __name__ == "__main__":
    main()

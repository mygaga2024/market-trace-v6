"""
Market Trace V6.0 — 启动入口
初始化消息总线、数据库、启动 5 Agent、启动 FastAPI
"""

import asyncio
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
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from loguru import logger

load_dotenv()

CONFIG_PATH = Path("config/settings.yaml")


def _resolve_env_vars(raw: str) -> str:
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
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
)
logger.add(sys.stdout, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
           colorize=True)

START_TIME = time.time()
bus = None
db = None
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
    rule_based = RuleBasedAnalyzer(llm_cfg)

    return LLMFallbackChain(primary, secondary, tertiary, rule_based)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bus, db, llm_chain, _agent_tasks

    from core.bus import MessageBus
    from db.database import Database

    redis_cfg = CONFIG["redis"]
    bus = MessageBus(
        host=redis_cfg["host"], port=redis_cfg["port"], db=redis_cfg["db"],
        password=redis_cfg["password"], max_connections=redis_cfg["max_connections"],
        retry_interval=redis_cfg["retry_interval"],
    )
    await bus.connect()
    logger.info("Redis 已连接")

    db_cfg = CONFIG.get("database", {})
    db = Database(database_url=db_cfg.get("url", "sqlite+aiosqlite:///data/market_trace.db"))
    await db.init()
    logger.info("数据库已初始化")

    llm_chain = _build_llm_chain(CONFIG)
    logger.info("LLM 回退链已就绪: DeepSeek → Gemini → MiniMax → 纯规则")

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


STOCK_POOL = [
    "000001","000002","000063","000333","000651","000725","000858",
    "002230","002415","002475","002594","300059","300750",
    "600000","600009","600016","600028","600030","600036","600048",
    "600050","600104","600276","600309","600519","600570","600585",
    "600690","600809","600837","600887","600900","601012","601088",
    "601166","601288","601318","601328","601390","601398","601601",
    "601628","601668","601688","601857","601888","601939","603259",
]


async def _analyze_single(symbol: str) -> dict:
    """核心分析逻辑：Tushare实时→AkShare→缓存降级→算指标→调LLM"""
    provider_cfg = [p for p in CONFIG.get("data_providers", []) if p.get("enabled")]
    tushare_token = next((p.get("token") for p in provider_cfg if p.get("name") == "tushare" and p.get("token")), None)
    cached = None

    if tushare_token:
        try:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            from data_provider.tushare_impl import TushareProvider
            tp = TushareProvider(bus, CONFIG, token=tushare_token)
            klines = await tp.fetch_kline(symbol, start_date, datetime.now().strftime("%Y%m%d"))
            if klines:
                cached = [{"close": k.close, "open": k.open, "high": k.high, "low": k.low, "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()} for k in klines]
        except Exception:
            pass

    if not cached:
        try:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            from data_provider.akshare_impl import AkShareProvider
            ap = AkShareProvider(bus, CONFIG)
            klines = await ap.fetch_kline(symbol, start_date, datetime.now().strftime("%Y%m%d"))
            if klines:
                cached = [{"close": k.close, "open": k.open, "high": k.high, "low": k.low, "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()} for k in klines]
        except Exception:
            pass

    if not cached and bus:
        cached = await bus.cache_get(f"market:raw:{symbol}")

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

    trace_agent = TraceAgent.__new__(TraceAgent)
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

    return {
        "symbol": symbol, "price": float(price), "change_pct": change_pct,
        "indicators": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "macd": macd, "rsi": rsi, "vol_ratio": vol_ratio},
        "trace_signals": [{"type": s["type"], "direction": s["direction"], "strength": s.get("strength", 0)} for s in trace_signals],
        "macro_rai": macro_rai, "decision": decision,
    }


@app.post("/analyze/{symbol}")
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
}


def _calc_rsi14(closes):
    from agents.signal_agent import SignalAgent
    r = SignalAgent._calc_rsi(np.array(closes), 14)
    return float(r[-1]) if r is not None and len(r) > 0 else 50


@app.post("/screen/{strategy}")
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


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Trace V6.0</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;padding:24px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}
.header h1{font-size:24px;background:linear-gradient(135deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.badge{padding:6px 14px;border-radius:20px;font-size:13px;font-weight:600}
.badge-ok{background:#1a3620;color:#3fb950}
.badge-warn{background:#3d2800;color:#d29922}
.badge-err{background:#3d1516;color:#f85149}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px}
.card-title{font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:12px;letter-spacing:1px}
.rai-value{font-size:56px;font-weight:700;line-height:1}
.rai-good{color:#3fb950}.rai-warm{color:#d29922}.rai-bad{color:#f85149}
.rai-label{font-size:14px;color:#8b949e;margin-top:4px}
.bar-bg{background:#21262d;border-radius:6px;height:8px;margin-top:8px;overflow:hidden}
.bar-fill{height:100%;border-radius:6px;transition:width .5s}
.agent-grid{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.agent-dot{display:flex;align-items:center;gap:6px;padding:6px 12px;background:#21262d;border-radius:8px;font-size:13px}
.agent-dot .dot{width:8px;height:8px;border-radius:50%}.dot-on{background:#3fb950}.dot-off{background:#f85149}
.llm-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #21262d}
.llm-row:last-child{border:none}
.llm-name{font-weight:600}.llm-status-on{color:#3fb950}.llm-status-off{color:#8b949e}
.links{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.links a{padding:6px 14px;background:#21262d;color:#58a6ff;text-decoration:none;border-radius:6px;font-size:13px;border:1px solid #30363d}
.links a:hover{background:#30363d}
.decision-box{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin-top:16px}
.decision-action{display:inline-block;padding:4px 12px;border-radius:6px;font-weight:700;font-size:14px;margin-right:8px}
.action-BUY{background:#1a3620;color:#3fb950}
.action-SELL{background:#3d1516;color:#f85149}
.action-HOLD{background:#21262d;color:#d29922}
.action-WAIT{background:#21262d;color:#8b949e}
.footer{text-align:center;color:#484f58;font-size:12px;margin-top:24px}
.refresh{font-size:12px;color:#484f58}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.pulse{animation:pulse 2s infinite}
.strat-btn{padding:8px 16px;background:#21262d;color:#58a6ff;border:1px solid #30363d;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600}
.strat-btn:hover{background:#30363d}
.result-card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;margin-bottom:10px}
.result-stats{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:8px}
.result-stat{text-align:center}.result-stat div:first-child{color:#8b949e;font-size:11px}.result-stat div:last-child{font-size:18px;font-weight:700;color:#c9d1d9}
.strat-result{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px;margin-bottom:8px;cursor:pointer}
.strat-result:hover{background:#21262d}
.strat-result .price{font-weight:700;color:#58a6ff}
</style>
<meta http-equiv="refresh" content="30">
</head>
<body>
<div class="header">
<h1>📊 Market Trace V6.0</h1>
<div style="display:flex;gap:8px;align-items:center">
<span id="sys-status" class="badge badge-ok">● 正常</span>
<span class="refresh">⏱ 30s刷新</span>
</div>
</div>

<div style="margin-bottom:20px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
<input id="stock-input" type="text" placeholder="输入股票代码 如 000001" style="flex:1;min-width:180px;padding:10px 16px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9;font-size:16px;outline:none" onkeydown="if(event.key==='Enter')analyzeStock()">
<button onclick="analyzeStock()" style="padding:10px 20px;background:#238636;border:none;border-radius:8px;color:white;font-size:16px;cursor:pointer;font-weight:600">🔍 诊股</button>
</div>
<div id="analyze-spinner" style="display:none;text-align:center;padding:10px;color:#58a6ff">⏳ 分析中，正在拉取数据+调用AI...</div>
<div id="analyze-result" style="display:none"></div>

<div class="grid">
<div class="card">
<div class="card-title">🧭 风险偏好指数 RAI</div>
<div id="rai-value" class="rai-value rai-warm">—</div>
<div id="rai-label" class="rai-label">加载中...</div>
<div class="bar-bg"><div id="rai-bar" class="bar-fill" style="width:50%;background:#d29922"></div></div>
</div>

<div class="card">
<div class="card-title">🤖 运行 Agent <span id="agent-count" style="color:#58a6ff">5/5</span></div>
<div class="agent-grid">
<div class="agent-dot"><span class="dot dot-on"></span>宏观 Macro</div>
<div class="agent-dot"><span class="dot dot-on"></span>信号 Signal</div>
<div class="agent-dot"><span class="dot dot-on"></span>资金 Trace</div>
<div class="agent-dot"><span class="dot dot-on"></span>风控 Risk</div>
<div class="agent-dot"><span class="dot dot-on"></span>决策 Chief</div>
</div>
</div>

<div class="card">
<div class="card-title">📡 AI 决策链</div>
<div id="llm-chain">加载中...</div>
</div>
</div>

<div id="decision-area" class="decision-box" style="display:none">
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
<span class="card-title" style="margin-bottom:0">📈 最新决策</span>
<span id="decision-action"></span>
<span style="color:#8b949e;font-size:13px">置信度 <strong id="decision-conf"></strong></span>
</div>
<div id="decision-reason" style="font-size:14px;color:#8b949e;line-height:1.6"></div>
<div style="margin-top:8px;font-size:12px;color:#484f58">AI: <span id="decision-provider"></span></div>
</div>

<div class="links">
<a href="/health">🩺 健康检查</a>
<a href="/status">📋 状态详情</a>
<a href="/reports/macro">📊 宏观报告</a>
<a href="/reports/signal">📉 信号报告</a>
<a href="/reports/trace">💹 资金报告</a>
<a href="/decisions">🧠 决策历史</a>
</div>

<div style="margin-top:20px">
<div class="card-title" style="margin-bottom:10px">🎯 选股策略</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
<button onclick="screenStocks('breakout')" class="strat-btn">🔥 强势突破</button>
<button onclick="screenStocks('oversold')" class="strat-btn">💎 超跌反弹</button>
<button onclick="screenStocks('strength')" class="strat-btn">💰 主力介入</button>
<button onclick="screenStocks('risk')" class="strat-btn">📉 风险预警</button>
</div>
<div id="screen-results" style="display:none"></div>
</div>

<div class="footer">
运行时间: <strong id="uptime">—</strong> &nbsp;|&nbsp;
版本 1.0.0 &nbsp;|&nbsp;
<a href="https://github.com/mygaga2024/market-trace-v6" style="color:#484f58">GitHub</a>
</div>

<script>
async function load(){
  try{
    let [h,st,mr,lr,dr] = await Promise.all([
      fetch('/health').then(r=>r.json()),
      fetch('/status').then(r=>r.json()),
      fetch('/reports/macro/latest').then(r=>r.ok?r.json():null),
      fetch('/reports/signal/latest').then(r=>r.ok?r.json():null),
      fetch('/reports/trace/latest').then(r=>r.ok?r.json():null),
    ]);

    // status
    let ok = h.status==='ok';
    document.getElementById('sys-status').className = 'badge '+(ok?'badge-ok':'badge-warn');
    document.getElementById('sys-status').innerText = ok?'● 正常':'● 降级';
    document.getElementById('uptime').innerText = fmtTime(h.uptime_seconds);

    // agents
    if(h.agents){
      let dots = document.querySelectorAll('.agent-dot .dot');
      let names = ['macro','signal','trace','risk','chief'];
      let alive = names.filter(n=>h.agents[n]).length;
      document.getElementById('agent-count').innerText = alive+'/5';
      names.forEach((n,i)=>{
        dots[i].className = 'dot '+(h.agents[n]?'dot-on':'dot-off');
      });
    }

    // LLM chain
    let llmHtml = '';
    if(h.llm_chain){
      for(let t of ['primary','secondary','tertiary']){
        let p = h.llm_chain[t];
        let icon = p.api_key_configured?'✓':'✗';
        let cls = p.api_key_configured?'llm-status-on':'llm-status-off';
        llmHtml += '<div class="llm-row"><span class="llm-name">'+icon+' '+p.provider+'</span><span style="font-size:12px;color:#8b949e">'+p.model+'</span></div>';
      }
    }
    document.getElementById('llm-chain').innerHTML = llmHtml || '未配置';

    // RAI
    if(mr && mr.data && mr.data.risk_appetite_index!=null){
      let rai = mr.data.risk_appetite_index;
      let interp = mr.data.interpretation || {};
      let cls = rai>=0.55?'rai-good':rai>=0.45?'rai-warm':'rai-bad';
      let pct = (rai*100).toFixed(0);
      document.getElementById('rai-value').innerHTML = rai.toFixed(2);
      document.getElementById('rai-value').className = 'rai-value '+cls;
      document.getElementById('rai-label').innerText = interp.regime || '';
      document.getElementById('rai-bar').style.width = pct+'%';
      document.getElementById('rai-bar').style.background = rai>=0.55?'#3fb950':rai>=0.45?'#d29922':'#f85149';
    } else {
      document.getElementById('rai-value').innerText = '—';
      document.getElementById('rai-label').innerText = '等待数据';
    }

    // decision
    let dec = st.latest_decision;
    if(dec){
      let area = document.getElementById('decision-area');
      area.style.display = 'block';
      document.getElementById('decision-action').innerHTML = '<span class="decision-action action-'+dec.action+'">'+dec.action+'</span>';
      document.getElementById('decision-conf').innerText = (dec.confidence*100).toFixed(0)+'%';
      document.getElementById('decision-reason').innerText = dec.reasoning || '';
      document.getElementById('decision-provider').innerText = dec.provider || '—';
    }

  }catch(e){console.error(e)}
}
function fmtTime(s){let m=Math.floor(s/60),h=Math.floor(m/60);m%=60;return h?h+'h'+m+'m':m+'m'+Math.floor(s%60)+'s'}
async function analyzeStock(){
  let sym=document.getElementById('stock-input').value.trim();
  if(!sym){alert('请输入股票代码');return}
  document.getElementById('analyze-spinner').style.display='block';
  document.getElementById('analyze-result').style.display='none';
  try{
    let r=await fetch('/analyze/'+sym,{method:'POST'});
    let d=await r.json();
    if(d.error){document.getElementById('analyze-result').innerHTML='<div class=\"card\" style=\"border-color:#f85149\">❌ '+d.error+'</div>'}
    else{
      let dec=d.decision;
      let html='<div class=\"result-card\"><div class=\"result-stats\"><div class=\"result-stat\"><div>价格</div><div>'+d.price.toFixed(2)+'</div></div><div class=\"result-stat\"><div>涨跌</div><div style=\"color:'+(d.change_pct>=0?'#3fb950':'#f85149')+'\">'+d.change_pct+'%</div></div><div class=\"result-stat\"><div>RSI</div><div>'+(d.indicators.rsi||'—')+'</div></div><div class=\"result-stat\"><div>量比</div><div>'+d.indicators.vol_ratio+'x</div></div></div>';
      if(d.indicators.macd&&d.indicators.macd.dif)html+='<div style=\"font-size:13px;color:#8b949e\">MACD: DIF='+d.indicators.macd.dif+' DEA='+d.indicators.macd.dea+' 柱='+d.indicators.macd.histogram+'</div>';
      if(d.trace_signals.length)html+='<div style=\"font-size:12px;margin-top:6px\">📊 '+d.trace_signals.map(s=>'<span style=\"color:'+(s.direction==='bullish'?'#3fb950':'#f85149')+'\">'+s.type+'</span>').join(' ')+'</div>';
      if(dec)html+='<div style=\"margin-top:12px;padding:12px;background:#0d1117;border-radius:8px\"><span class=\"decision-action action-'+dec.action+'\">'+dec.action+'</span> <span style=\"font-size:13px\">置信度 '+(dec.confidence*100).toFixed(0)+'%</span><div style=\"margin-top:6px;font-size:13px;color:#8b949e\">'+dec.reasoning+'</div><div style=\"font-size:11px;color:#484f58;margin-top:4px\">AI: '+dec.provider+' | RAI宏观: '+d.macro_rai.toFixed(2)+'</div></div>';
      html+='</div>';
      document.getElementById('analyze-result').innerHTML=html;
    }
    document.getElementById('analyze-result').style.display='block';
  }catch(e){document.getElementById('analyze-result').innerHTML='<div class=\"card\" style=\"border-color:#f85149\">请求失败: '+e.message+'</div>';document.getElementById('analyze-result').style.display='block'}
  document.getElementById('analyze-spinner').style.display='none';
}
async function screenStocks(strategy){
  document.getElementById('screen-results').style.display='block';
  document.getElementById('screen-results').innerHTML='<div style=\"text-align:center;color:#58a6ff;padding:10px\">⏳ 扫描中...</div>';
  try{
    let r=await fetch('/screen/'+strategy,{method:'POST'});
    let d=await r.json();
    if(d.error){document.getElementById('screen-results').innerHTML='<div style=\"color:#f85149\">'+d.error+'</div>';return}
    let html='<div style=\"font-size:13px;color:#8b949e;margin-bottom:10px\">📋 '+d.strategy+' — 匹配 '+d.matched+' 只</div>';
    d.results.forEach(s=>{html+='<div class=\"strat-result\" onclick=\"document.getElementById(\'stock-input\').value=\''+s.symbol+'\';analyzeStock()\"><span class=\"price\">'+s.symbol+'</span> '+s.price.toFixed(2)+' <span style=\"color:'+(s.change_pct>=0?'#3fb950':'#f85149')+'\">'+s.change_pct+'%</span> <span style=\"color:#8b949e\">量比 '+s.vol_ratio+'x</span></div>'});
    document.getElementById('screen-results').innerHTML=html;
  }catch(e){document.getElementById('screen-results').innerHTML='<div style=\"color:#f85149\">'+e.message+'</div>'}
}
load();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


def main():
    logger.info("Market Trace V6.0 正在启动...")
    logger.info("LLM: {}::{}", CONFIG["llm"]["primary"]["provider"], CONFIG["llm"]["primary"]["model"])
    logger.info("数据源: {}", [p["name"] for p in CONFIG["data_providers"] if p.get("enabled")])
    uvicorn.run("main:app", host="0.0.0.0", port=19377, log_config=None, access_log=False)


if __name__ == "__main__":
    main()

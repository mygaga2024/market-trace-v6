"""
Market Trace V6.0 — 启动入口
初始化消息总线、数据库、启动 5 Agent、启动 FastAPI
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import yaml
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from core.log_filter import desensitize as log_filter

load_dotenv()

CONFIG_PATH = Path("config/settings.yaml")


def _resolve_env_vars(raw: str) -> str:
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
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
        "deepseek-reasoner", llm_cfg.get("secondary", {}),
        CircuitBreaker(name="llm:deepseek-reasoner", **cb_kwargs),
    )
    tertiary = OpenAICompatibleLLM(
        "gemini", llm_cfg.get("tertiary", {}),
        CircuitBreaker(name="llm:gemini", **cb_kwargs),
    )
    quaternary = OpenAICompatibleLLM(
        "gemini-k2", llm_cfg.get("quaternary", {}),
        CircuitBreaker(name="llm:gemini-k2", **cb_kwargs),
    )
    quinary = OpenAICompatibleLLM(
        "minimax-s", llm_cfg.get("quinary", {}),
        CircuitBreaker(name="llm:minimax-s", **cb_kwargs),
    )
    septenary = OpenAICompatibleLLM(
        "zhipu-flash", llm_cfg.get("septenary", {}),
        CircuitBreaker(name="llm:zhipu-flash", **cb_kwargs),
    )
    octonary = OpenAICompatibleLLM(
        "zhipu-plus", llm_cfg.get("octonary", {}),
        CircuitBreaker(name="llm:zhipu-plus", **cb_kwargs),
    )
    rule_based = RuleBasedAnalyzer(llm_cfg.get("fallback", {}))

    return LLMFallbackChain(primary, secondary, tertiary, quaternary, quinary, septenary, octonary, rule_based)


def _start_agents(bus, config: dict, llm_chain, risk_manager=None) -> list[asyncio.Task]:
    from data_provider.akshare_impl import AkShareProvider
    from data_provider.tushare_impl import TushareProvider
    from core.memory import CaseMemory
    from agents.macro_agent import MacroAgent
    from agents.signal_agent import SignalAgent
    from agents.trace_agent import TraceAgent
    from agents.risk_agent import RiskAgent
    from agents.chief_analyst import ChiefAnalyst

    tasks: list[asyncio.Task] = []

    ak_provider = AkShareProvider(bus, config)

    tushare_cfg = [p for p in config.get("data_providers", []) if p.get("name") == "tushare" and p.get("enabled")]
    if tushare_cfg and tushare_cfg[0].get("token"):
        # TushareProvider 构造函数将自身注册为备用数据源，无需保存引用
        TushareProvider(bus, config, token=tushare_cfg[0]["token"])
        logger.info("Tushare 数据源已启用")

    macro = MacroAgent(bus, config, data_provider=ak_provider)
    tasks.append(asyncio.create_task(macro.start(), name="macro-agent"))

    memory = CaseMemory(max_cases=10000)
    signal = SignalAgent(bus, config, memory=memory)
    tasks.append(asyncio.create_task(signal.start(), name="signal-agent"))

    trace = TraceAgent(bus, config)
    tasks.append(asyncio.create_task(trace.start(), name="trace-agent"))

    risk = RiskAgent(bus, config, risk_manager=risk_manager)
    tasks.append(asyncio.create_task(risk.start(), name="risk-agent"))

    chief = ChiefAnalyst(bus, config, llm_chain=llm_chain)
    tasks.append(asyncio.create_task(chief.start(), name="chief-agent"))

    return tasks


async def _backtest_scheduler(_bus, config: dict, _sm, schedule_cfg: dict):
    """后台定时回测任务"""
    time_str = schedule_cfg.get("time", "18:00")
    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, TypeError):
        hour, minute = 18, 0

    while True:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        wait = (next_run - now).total_seconds()
        logger.info("定时回测: 下次运行 {} ({}s后)", next_run.strftime("%Y-%m-%d %H:%M"), int(wait))
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return

        if not _bus:
            logger.warning("定时回测跳过: 消息总线未就绪")
            continue

        try:
            from backtest.strategy_backtest import run_strategy_backtest
            active = await _sm.get_active_strategies()
            if not active:
                logger.warning("定时回测跳过: 无活跃策略")
                continue
            stocks = config.get("stock_pool", [])[:20]
            results = await run_strategy_backtest(_bus, config, stocks, active_strategies=active)
            changes = await _sm.evaluate_health(results)
            logger.info("定时回测完成: {} 只股票, {} 个策略, 变更: {}", len(results), len(active), changes)
        except Exception as e:
            logger.error("定时回测异常: {}", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.bus import MessageBus
    from core.notifier import get_notifier
    from db.database import Database

    # ── 初始化共享状态 ──
    app.state.config = CONFIG
    app.state.start_time = time.time()
    app.state.agent_tasks = []

    # Redis
    redis_cfg = CONFIG["redis"]
    bus_instance = MessageBus(
        host=redis_cfg["host"], port=redis_cfg["port"], db=redis_cfg["db"],
        password=redis_cfg["password"], max_connections=redis_cfg["max_connections"],
        retry_interval=redis_cfg["retry_interval"],
    )
    try:
        await bus_instance.connect(max_retries=3)
        app.state.bus = bus_instance
        logger.info("Redis 已连接")
    except Exception:
        logger.warning("Redis 不可用，将以无 Redis 模式运行")
        app.state.bus = None

    # Database
    db_cfg = CONFIG.get("database", {})
    db = Database(database_url=db_cfg.get("url", "sqlite+aiosqlite:///data/market_trace.db"))
    await db.init()
    app.state.db = db
    logger.info("数据库已初始化")

    # LLM
    llm_chain = _build_llm_chain(CONFIG)
    app.state.llm_chain = llm_chain
    logger.info("LLM 回退链已就绪: DS Chat → DS Reasoner → Gemini K1 → Gemini K2 → MM-S → MM → GLM Flash → GLM Plus → 纯规则")

    # Notifier
    notifier = get_notifier()
    app.state.notifier = notifier
    if notifier.enabled:
        logger.info("微信通知已启用")
    else:
        logger.info("微信通知未配置 (设置 WXPUSHER_TOKEN + WXPUSHER_UID)")

    # Risk Manager
    from core.risk_manager import RiskManager
    risk_manager = RiskManager(app.state.bus, CONFIG)
    app.state.risk_manager = risk_manager
    logger.info("风控闭环管理器已就绪")

    # Agents
    agent_tasks = _start_agents(app.state.bus, CONFIG, llm_chain, risk_manager)
    app.state.agent_tasks = agent_tasks
    logger.info("{} 个 Agent 已启动", len(agent_tasks))

    # Prefetch (保存 task 引用防止 GC)
    from services.prefetch import prefetch_stock_pool, prefetch_stock_names
    prefetch_task = asyncio.create_task(prefetch_stock_pool(app.state.bus, CONFIG))
    agent_tasks.append(prefetch_task)

    name_task = asyncio.create_task(prefetch_stock_names(app.state.bus, CONFIG))
    agent_tasks.append(name_task)

    # Strategy Manager
    from backtest.strategy_manager import StrategyManager
    bt_cfg = CONFIG.get("backtest", {})
    strategy_manager = StrategyManager(
        app.state.bus,
        consecutive_loss_threshold=bt_cfg.get("consecutive_loss_threshold", 10),
        min_win_rate=bt_cfg.get("min_win_rate", 0.35),
        min_score=bt_cfg.get("min_score", -1.0),
        min_total_trades=bt_cfg.get("min_total_trades", 3),
    )
    app.state.strategy_manager = strategy_manager

    schedule_cfg = bt_cfg.get("schedule", {})
    if schedule_cfg.get("enabled", False):
        bt_task = asyncio.create_task(
            _backtest_scheduler(app.state.bus, CONFIG, strategy_manager, schedule_cfg)
        )
        agent_tasks.append(bt_task)
        logger.info("定时回测已启用: 每日 {}", schedule_cfg.get("time", "18:00"))

    yield

    # ── Shutdown ──
    logger.info("正在停止所有 Agent...")
    for task in agent_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*agent_tasks, return_exceptions=True)
    logger.info("所有 Agent 已停止")

    if llm_chain:
        try:
            await llm_chain.close()
        except Exception:
            pass
    if notifier:
        try:
            await notifier.close()
        except Exception:
            pass
    if db:
        await db.close()
    if app.state.bus:
        await app.state.bus.close()
    logger.info("系统已关闭")


# ── FastAPI App ──

app = FastAPI(
    title="Market Trace V6.0",
    description="A/B 股量化分析系统 — 多 Agent 协作 + AI 决策",
    version="1.1.8",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# 挂载路由
from api.health import router as health_router
from api.reports import router as reports_router
from api.analyze import router as analyze_router
from api.backtest import router as backtest_router
from api.risk import router as risk_router
from api.kline import router as kline_router
from api.watchlist import router as watchlist_router
from api.paper import router as paper_router
from api.replay import router as replay_router

app.include_router(health_router)
app.include_router(reports_router)
app.include_router(analyze_router)
app.include_router(backtest_router)
app.include_router(risk_router)
app.include_router(kline_router)
app.include_router(watchlist_router)
app.include_router(paper_router)
app.include_router(replay_router)


def main():
    logger.info("Market Trace V6.0 正在启动...")

    # M1: 必需环境变量启动校验
    llm_cfg = CONFIG.get("llm", {})
    for tier, key in [("主力(DS Chat)", "primary"), ("主力备选(DS Reasoner)", "secondary"), ("备用K1(Gemini)", "tertiary"), ("备用K2(Gemini备胎)", "quaternary"), ("三级兜底(MM-S)", "quinary"), ("三级备选(MM)", "senary"), ("四级(GLM免费)", "septenary"), ("五级(GLM收费)", "octonary")]:
        api_key = llm_cfg.get(key, {}).get("api_key", "")
        if not api_key or "your-" in api_key:
            logger.warning("⚠️ {} LLM ({}) API Key 未配置，该级别将无法使用", tier, key)

    logger.info("LLM: {}::{}", CONFIG["llm"]["primary"]["provider"], CONFIG["llm"]["primary"]["model"])
    logger.info("数据源: {}", [p["name"] for p in CONFIG["data_providers"] if p.get("enabled")])
    uvicorn.run("main:app", host="0.0.0.0", port=19377, log_config=None, access_log=False)


if __name__ == "__main__":
    main()

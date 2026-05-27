"""
Market Trace V6.0 — 启动入口
初始化消息总线、数据库、启动 FastAPI、注册 Agent
"""

import os
import sys
import time
from pathlib import Path
from contextlib import asynccontextmanager

import yaml
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
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
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    colorize=True,
)

START_TIME = time.time()
bus = None
db = None
llm_chain = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bus, db, llm_chain

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

    yield

    if db:
        await db.close()
    if bus:
        await bus.close()
    logger.info("系统已关闭")


app = FastAPI(
    title="Market Trace V6.0",
    description="A/B 股量化分析系统 — 多 Agent 协作 + AI 决策",
    version="0.7.0",
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
        "version": "0.7.0",
        "uptime_seconds": round(uptime, 1),
        "redis": "connected" if redis_ok else "disconnected",
        "database": "connected" if db_ok else "disconnected",
        "agents": agents,
        "llm_chain": llm_status,
    }


@app.get("/status")
async def status():
    response = {
        "version": "0.7.0",
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }

    if db:
        try:
            stats = await db.get_decision_stats()
            response["decision_stats"] = stats
            latest = await db.get_latest_decision()
            if latest:
                response["latest_decision"] = {
                    "action": latest.action,
                    "confidence": latest.confidence,
                    "reasoning": latest.reasoning[:200],
                    "provider": latest.provider_label,
                    "timestamp": latest.timestamp.isoformat(),
                }
        except Exception as e:
            response["decision_stats"] = {"error": str(e)}

    if db:
        try:
            case_stats = await db.get_case_statistics()
            response["case_stats"] = case_stats
        except Exception:
            response["case_stats"] = {"error": "unavailable"}

    return response


@app.get("/reports/{agent_name}")
async def get_reports(
    agent_name: str,
    symbol: str = Query(None, description="按标的过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    valid_agents = {"macro", "signal", "trace", "risk", "chief"}
    if agent_name not in valid_agents:
        return JSONResponse(
            {"error": f"无效 Agent: {agent_name}，可选: {sorted(valid_agents)}"},
            status_code=400,
        )

    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)

    try:
        reports = await db.get_reports(agent=agent_name, limit=limit, offset=offset)
        return {
            "agent": agent_name,
            "count": len(reports),
            "items": [
                {
                    "report_id": r.report_id,
                    "agent": r.agent,
                    "symbol": r.symbol,
                    "summary": r.summary,
                    "confidence": r.confidence,
                    "status": r.status,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "data": r.data,
                }
                for r in reports
            ],
        }
    except Exception as e:
        logger.error("获取报告失败: {}", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/reports/{agent_name}/latest")
async def get_latest_report(agent_name: str, symbol: str = Query(None)):
    valid_agents = {"macro", "signal", "trace", "risk", "chief"}
    if agent_name not in valid_agents:
        return JSONResponse({"error": f"无效 Agent: {agent_name}"}, status_code=400)
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)

    try:
        r = await db.get_latest_report(agent_name, symbol=symbol)
        if not r:
            return JSONResponse({"error": f"Agent {agent_name} 无最新报告"}, status_code=404)
        return {
            "report_id": r.report_id,
            "agent": r.agent,
            "symbol": r.symbol,
            "summary": r.summary,
            "confidence": r.confidence,
            "status": r.status,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "data": r.data,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/decisions")
async def get_decisions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)

    try:
        decisions = await db.get_decisions(limit=limit, offset=offset)
        stats = await db.get_decision_stats()
        return {
            "count": len(decisions),
            "stats": stats,
            "items": [
                {
                    "decision_id": d.decision_id,
                    "action": d.action,
                    "confidence": d.confidence,
                    "reasoning": d.reasoning[:300],
                    "evidence_sources": d.evidence_sources,
                    "risk_override": d.risk_override,
                    "provider_label": d.provider_label,
                    "provider_status": d.provider_status,
                    "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                }
                for d in decisions
            ],
        }
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
            return {
                "decision_id": d.decision_id,
                "action": d.action,
                "confidence": d.confidence,
                "reasoning": d.reasoning,
                "evidence_sources": d.evidence_sources,
                "evidence_chain": d.evidence_chain,
                "risk_override": d.risk_override,
                "provider_label": d.provider_label,
                "provider_status": d.provider_status,
                "timestamp": d.timestamp.isoformat() if d.timestamp else None,
            }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def main():
    logger.info("Market Trace V6.0 正在启动...")
    logger.info("LLM 主力: {}::{}", CONFIG["llm"]["primary"]["provider"], CONFIG["llm"]["primary"]["model"])
    logger.info("数据源: {}", [p["name"] for p in CONFIG["data_providers"] if p.get("enabled")])
    logger.info("数据库: {}", CONFIG.get("database", {}).get("url", "sqlite+aiosqlite:///data/market_trace.db"))

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_config=None, access_log=False)


if __name__ == "__main__":
    main()

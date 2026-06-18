"""
Market Trace V6.0 — 健康检查与系统状态路由
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from loguru import logger

from api.deps import verify_token

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    """健康检查（公开端点，运维探活用，精简返回避免泄露内部架构）"""
    bus = request.app.state.bus
    db = request.app.state.db

    redis_ok = False
    db_ok = False
    if bus:
        try:
            redis_ok = await bus.health_check()
        except Exception:
            pass

    if db:
        try:
            db_ok = await db.health_check()
        except Exception:
            pass

    all_ok = redis_ok and db_ok
    uptime = time.time() - request.app.state.start_time

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "1.1.5",
        "uptime_seconds": round(uptime, 1),
    }


@router.get("/health/detail", dependencies=[Depends(verify_token)])
async def health_detail(request: Request):
    """详细健康检查（需认证，包含 Agent/LLM/Redis 状态）"""
    bus = request.app.state.bus
    db = request.app.state.db
    config = request.app.state.config
    agent_tasks = request.app.state.agent_tasks

    redis_ok = False
    db_ok = False
    if bus:
        try:
            redis_ok = await bus.health_check()
        except Exception:
            pass

    if db:
        try:
            db_ok = await db.health_check()
        except Exception:
            pass

    agents = {}
    if bus and redis_ok:
        try:
            agents = await bus.check_all_heartbeats(["macro", "signal", "trace", "risk", "chief"])
        except Exception:
            pass

    llm_status = {}
    llm_cfg = config.get("llm", {})
    for tier, key in [("primary", "primary"), ("secondary", "secondary"), ("tertiary", "tertiary"), ("quaternary", "quaternary"), ("quinary", "quinary"), ("senary", "senary"), ("septenary", "septenary"), ("octonary", "octonary")]:
        provider = llm_cfg.get(key, {})
        llm_status[key] = {
            "api_key_configured": bool(provider.get("api_key") and "your-" not in str(provider.get("api_key", ""))),
            "provider": provider.get("provider", key),
            "model": provider.get("model", ""),
        }

    uptime = time.time() - request.app.state.start_time
    all_ok = redis_ok and db_ok

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "1.1.5",
        "uptime_seconds": round(uptime, 1),
        "redis": "connected" if redis_ok else "disconnected",
        "database": "connected" if db_ok else "disconnected",
        "agents": agents,
        "llm_chain": llm_status,
        "agents_running": len([t for t in agent_tasks if not t.done()]),
    }


@router.get("/status", dependencies=[Depends(verify_token)])
async def status(request: Request):
    """系统状态详情（需认证）"""
    db = request.app.state.db
    response: dict[str, Any] = {
        "version": "1.1.3",
        "uptime_seconds": round(time.time() - request.app.state.start_time, 1),
    }

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
        except Exception:
            response["decision_stats"] = {"error": "获取决策统计失败"}

        try:
            response["case_stats"] = await db.get_case_statistics()
        except Exception:
            response["case_stats"] = {"error": "获取案例统计失败"}

    return response


@router.get("/logs", dependencies=[Depends(verify_token)])
async def system_logs(request: Request, lines: int = 100):
    """获取最近系统日志（需认证）"""
    import asyncio as _asyncio
    from datetime import date as _date
    from pathlib import Path as _Path

    log_path = _Path("logs") / f"market_trace_{_date.today().strftime('%Y-%m-%d')}.log"

    if not log_path.exists():
        log_files = sorted(_Path("logs").glob("market_trace_*.log"), reverse=True)
        if log_files:
            log_path = log_files[0]
        else:
            return {"error": "日志文件不存在", "lines": []}

    try:
        result = await _asyncio.to_thread(
            lambda: log_path.read_text(encoding="utf-8").strip().split("\n")[-lines:]
        )
        return {"file": log_path.name, "count": len(result), "lines": result}
    except Exception as e:
        return {"error": str(e), "lines": []}

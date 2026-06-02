"""
Market Trace V6.0 — 报告与决策路由
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token

router = APIRouter(tags=["reports"], dependencies=[Depends(verify_token)])


@router.get("/reports/{agent_name}")
async def get_reports(request: Request, agent_name: str, symbol: str = Query(None),
                      limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    valid = {"macro", "signal", "trace", "risk", "chief"}
    if agent_name not in valid:
        return JSONResponse({"error": f"无效 Agent: {agent_name}，可选: {sorted(valid)}"}, status_code=400)
    db = request.app.state.db
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
        logger.error("获取报告失败: {}", e)
        return JSONResponse({"error": "服务器内部错误"}, status_code=500)


@router.get("/reports/{agent_name}/latest")
async def get_latest_report(request: Request, agent_name: str, symbol: str = Query(None)):
    valid = {"macro", "signal", "trace", "risk", "chief"}
    if agent_name not in valid:
        return JSONResponse({"error": f"无效 Agent: {agent_name}"}, status_code=400)
    db = request.app.state.db
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
        logger.error("获取最新报告失败: {}", e)
        return JSONResponse({"error": "服务器内部错误"}, status_code=500)


@router.get("/decisions")
async def get_decisions(request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    db = request.app.state.db
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
        logger.error("获取决策列表失败: {}", e)
        return JSONResponse({"error": "服务器内部错误"}, status_code=500)


@router.get("/decisions/{decision_id}")
async def get_decision(request: Request, decision_id: str):
    db = request.app.state.db
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        d = await db.get_decision_by_id(decision_id)
        if not d:
            return JSONResponse({"error": f"决策 {decision_id} 不存在"}, status_code=404)
        return {"decision_id": d.decision_id, "action": d.action, "confidence": d.confidence,
                "reasoning": d.reasoning, "evidence_sources": d.evidence_sources,
                "evidence_chain": d.evidence_chain, "risk_override": d.risk_override,
                "provider_label": d.provider_label, "provider_status": d.provider_status,
                "timestamp": d.timestamp.isoformat() if d.timestamp else None}
    except Exception as e:
        logger.error("获取决策详情失败: {}", e)
        return JSONResponse({"error": "服务器内部错误"}, status_code=500)

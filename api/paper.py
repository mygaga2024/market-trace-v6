"""
Market Trace V6.0 — 纸上交易路由
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token

router = APIRouter(prefix="/paper", tags=["paper"], dependencies=[Depends(verify_token)])


@router.get("/account/{account_id}")
async def paper_account(request: Request, account_id: str = "default"):
    """获取纸上账户摘要"""
    from core.paper_trader import get_paper_manager
    try:
        pm = get_paper_manager(getattr(request.app.state, "bus", None))
        summary = await pm.get_summary(account_id)
        return summary
    except Exception as e:
        logger.error("纸上账户查询失败: {}", e)
        return JSONResponse({"error": "纸上账户查询失败"}, status_code=500)


@router.post("/execute")
async def paper_execute(
    request: Request,
    symbol: str = Query(...),
    decision: str = Query(default="BUY"),
    price: float = Query(gt=0),
    confidence: float = Query(default=0.5, ge=0, le=1),
    reason: str = Query(default=""),
    account_id: str = Query(default="default"),
):
    """执行纸上交易"""
    from core.paper_trader import get_paper_manager
    try:
        pm = get_paper_manager(getattr(request.app.state, "bus", None))
        result = await pm.execute_signal(
            symbol, decision, price,
            confidence=confidence, account_id=account_id, reason=reason,
        )
        return result or {"error": "交易执行失败"}
    except Exception as e:
        logger.error("纸上交易执行失败: {}", e)
        return JSONResponse({"error": "纸上交易执行失败"}, status_code=500)

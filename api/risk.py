"""
Market Trace V6.0 — 风控路由
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token

router = APIRouter(prefix="/risk", tags=["risk"], dependencies=[Depends(verify_token)])


@router.get("/status")
async def risk_status(request: Request):
    """风控闭环当前状态：风险等级、否决次数、熔断状态"""
    risk_manager = request.app.state.risk_manager
    if not risk_manager:
        return JSONResponse({"error": "风控管理器未就绪"}, status_code=503)
    try:
        state = await risk_manager.get_risk_state()
        return state
    except Exception as e:
        logger.error("获取风控状态失败: {}", e)
        return JSONResponse({"error": "获取风控状态失败"}, status_code=500)


@router.get("/overrides")
async def risk_overrides(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    """风控否决事件历史"""
    risk_manager = request.app.state.risk_manager
    if not risk_manager:
        return JSONResponse({"error": "风控管理器未就绪"}, status_code=503)
    try:
        history = await risk_manager.get_override_history(limit)
        return {"count": len(history), "overrides": history}
    except Exception as e:
        logger.error("获取风控历史失败: {}", e)
        return JSONResponse({"error": "获取风控历史失败"}, status_code=500)


@router.get("/position/{symbol}")
async def risk_position(
    request: Request,
    symbol: str,
    method: str = Query(default="kelly"),
    capital: float = Query(default=100000, ge=1000),
    price: float = Query(default=10.0, gt=0),
    win_prob: float = Query(default=0.5, ge=0, le=1),
    avg_win: float = Query(default=0.03, gt=0),
    avg_loss: float = Query(default=0.02, gt=0),
):
    """风控加权仓位建议：根据当前风险等级调整仓位"""
    risk_manager = request.app.state.risk_manager
    if not risk_manager:
        return JSONResponse({"error": "风控管理器未就绪"}, status_code=503)
    try:
        suggestion = await risk_manager.get_position_suggestion(
            symbol, capital=capital, price=price, method=method,
            win_prob=win_prob, avg_win=avg_win, avg_loss=avg_loss,
        )
        return suggestion
    except Exception as e:
        logger.error("仓位建议失败: {}", e)
        return JSONResponse({"error": "获取仓位建议失败"}, status_code=500)

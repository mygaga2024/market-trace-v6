"""
Market Trace V6.0 — 大盘指数路由
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token

router = APIRouter(tags=["market_index"])


@router.get("/api/market/index", dependencies=[Depends(verify_token)])
async def market_index(request: Request):
    """获取大盘指数实时行情（上证/深证/创业板/科创50/沪深300）"""
    bus = request.app.state.bus
    if not bus:
        return JSONResponse({"error": "数据总线未就绪", "indices": []}, status_code=503)

    try:
        cached = await bus.cache_get("market:macro")
        if not cached or not cached.get("raw"):
            return JSONResponse({
                "indices": [],
                "message": "指数数据暂未就绪，请等待 Macro Agent 首次采集",
            })

        raw = cached["raw"]
        indices = raw.get("indices", [])

        if not indices:
            return JSONResponse({
                "indices": [],
                "message": "指数数据为空",
            })

        return {
            "indices": indices,
            "timestamp": cached.get("timestamp") or raw.get("timestamp"),
            "source": cached.get("source") or raw.get("source"),
        }
    except Exception as e:
        logger.error("获取大盘指数失败: {}", e)
        return JSONResponse({"error": "获取大盘指数失败", "indices": []}, status_code=500)

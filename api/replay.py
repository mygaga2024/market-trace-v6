"""
Market Trace V6.0 — 历史行情重放路由
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token

router = APIRouter(prefix="/replay", tags=["replay"], dependencies=[Depends(verify_token)])

_replayer_instance = None


def _get_replayer(bus):
    global _replayer_instance
    if _replayer_instance is None:
        from backtest.replay import MarketReplay
        _replayer_instance = MarketReplay(bus)
    return _replayer_instance


@router.post("/start")
async def replay_start(
    request: Request,
    symbol: str = Query(...),
    speed: float = Query(default=0.0, ge=0),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    max_events: int = Query(default=0, ge=0),
):
    """启动历史行情重放"""
    from backtest.replay import ReplayConfig
    try:
        bus = getattr(request.app.state, "bus", None)
        if not bus:
            return JSONResponse({"error": "消息总线未就绪"}, status_code=503)

        cached = await bus.cache_get(f"market:raw:{symbol}")
        if not cached or len(cached) < 5:
            return JSONResponse({"error": f"{symbol} 缓存数据不足"}, status_code=400)

        config = ReplayConfig(
            symbol=symbol, speed=speed,
            start_date=start_date or None,
            end_date=end_date or None,
            max_events=max_events,
        )
        replayer = _get_replayer(bus)
        progress = await replayer.replay(config, cached)
        return {
            "symbol": symbol, "speed": speed,
            "total": progress.total, "processed": progress.processed,
            "errors": progress.errors, "done": progress.done,
        }
    except Exception as e:
        logger.error("重放启动失败: {}", e)
        return JSONResponse({"error": "重放启动失败"}, status_code=500)


@router.post("/stop")
async def replay_stop(request: Request):
    """停止重放"""
    global _replayer_instance
    if _replayer_instance is None:
        return JSONResponse({"error": "无活跃重放"}, status_code=404)
    _replayer_instance.stop()
    return {"stopped": True}


@router.get("/progress/{symbol}")
async def replay_progress(request: Request, symbol: str):
    """查询重放进度"""
    global _replayer_instance
    if _replayer_instance is None:
        return JSONResponse({"error": "无活跃重放"}, status_code=404)
    progress = _replayer_instance.get_progress(symbol)
    if progress is None:
        return JSONResponse({"error": f"无 {symbol} 重放进度"}, status_code=404)
    return {
        "symbol": symbol, "total": progress.total,
        "processed": progress.processed, "errors": progress.errors,
        "pct": round(progress.pct, 1), "done": progress.done,
    }

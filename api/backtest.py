"""
Market Trace V6.0 — 回测路由
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token

router = APIRouter(prefix="/backtest", tags=["backtest"], dependencies=[Depends(verify_token)])


@router.get("/summary")
async def backtest_summary(request: Request):
    """策略回测：仅活跃策略 × 股票池 → 夏普/回撤/胜率排行"""
    bus = request.app.state.bus
    config = request.app.state.config
    strategy_manager = request.app.state.strategy_manager
    stock_pool = config.get("stock_pool", [])

    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from backtest.strategy_backtest import run_strategy_backtest
        active = await strategy_manager.get_active_strategies() if strategy_manager else None
        results = await run_strategy_backtest(bus, config, stock_pool, active_strategies=active)
        if strategy_manager:
            await strategy_manager.evaluate_health(results)
        total = sum(len(v) for v in results.values())
        return {"count": total, "results": results}
    except Exception as e:
        logger.error("回测汇总失败: {}", e)
        return JSONResponse({"error": "回测执行失败"}, status_code=500)


@router.get("/strategies")
async def backtest_strategies(request: Request):
    """所有回测策略的状态、连续失败数、是否被禁用"""
    strategy_manager = request.app.state.strategy_manager
    if not strategy_manager:
        return JSONResponse({"error": "策略管理器未就绪"}, status_code=503)
    try:
        all_strategies = await strategy_manager.get_all_strategies()
        return {"strategies": all_strategies}
    except Exception as e:
        logger.error("获取策略列表失败: {}", e)
        return JSONResponse({"error": "获取策略列表失败"}, status_code=500)


@router.post("/strategies/{name}/enable")
async def backtest_strategy_enable(request: Request, name: str):
    """重新启用已被禁用的策略"""
    strategy_manager = request.app.state.strategy_manager
    if not strategy_manager:
        return JSONResponse({"error": "策略管理器未就绪"}, status_code=503)
    try:
        await strategy_manager.enable_strategy(name)
        return {"strategy": name, "status": "active"}
    except Exception as e:
        logger.error("启用策略失败: {}", e)
        return JSONResponse({"error": "启用策略失败"}, status_code=500)


@router.get("/rolling/{symbol}")
async def backtest_rolling(request: Request, symbol: str, strategy: str = "breakout"):
    """滚动窗口样本外验证"""
    bus = request.app.state.bus
    config = request.app.state.config
    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from backtest.strategy_backtest import run_rolling_backtest
        result = await run_rolling_backtest(bus, config, symbol, strategy)
        return result
    except Exception as e:
        logger.error("滚动回测失败: {}", e)
        return JSONResponse({"error": "滚动回测执行失败"}, status_code=500)


@router.post("/run")
async def backtest_run(request: Request, optimize: bool = False):
    """手动触发一次回测，可选参数优化"""
    bus = request.app.state.bus
    config = request.app.state.config
    strategy_manager = request.app.state.strategy_manager
    stock_pool = config.get("stock_pool", [])

    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from backtest.strategy_backtest import run_strategy_backtest
        active = await strategy_manager.get_active_strategies() if strategy_manager else None
        results = await run_strategy_backtest(bus, config, stock_pool, active_strategies=active, optimize=optimize)
        changes = await strategy_manager.evaluate_health(results) if strategy_manager else {}
        return {"count": sum(len(v) for v in results.values()), "results": results, "strategy_changes": changes}
    except Exception as e:
        logger.error("手动回测失败: {}", e)
        return JSONResponse({"error": "回测执行失败"}, status_code=500)

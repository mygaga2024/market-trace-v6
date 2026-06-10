"""
Market Trace V6.0 — 诊股与选股路由
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token
from core.strategies import STRATEGIES
from services.analyzer import analyze_single
from services.prefetch import ensure_symbol_cached, get_prefetch_providers, get_stock_name

router = APIRouter(tags=["analyze"], dependencies=[Depends(verify_token)])


@router.post("/analyze/{symbol}")
async def analyze_stock(request: Request, symbol: str):
    """诊股：拉数据→增强技术分析→策略信号→AI决策"""
    bus = request.app.state.bus
    config = request.app.state.config
    llm_chain = request.app.state.llm_chain
    tp, ap = get_prefetch_providers()
    try:
        await ensure_symbol_cached(symbol, bus, config)
        result = await analyze_single(symbol, bus, config, llm_chain, prefetch_tp=tp, prefetch_ap=ap)
        return result
    except Exception as e:
        from fastapi import HTTPException
        if isinstance(e, HTTPException):
            raise
        logger.error("诊股失败 {}: {}", symbol, e)
        return JSONResponse({"error": "诊股分析失败，请稍后重试", "symbol": symbol}, status_code=500)


@router.post("/screen/{strategy}")
async def screen_stocks(request: Request, strategy: str):
    """选股：按策略并发扫描股票池（复用统一策略定义）"""
    if strategy not in STRATEGIES:
        return JSONResponse({"error": f"策略不存在: {strategy}，可选: {list(STRATEGIES.keys())}"}, status_code=400)

    bus = request.app.state.bus
    config = request.app.state.config
    stock_pool = config.get("stock_pool", [])
    info = STRATEGIES[strategy]
    strategy_name = info["label"]
    check_fn = info["check"]
    default_params = info.get("params", {}).copy()

    async def _check_symbol(symbol: str) -> dict | None:
        try:
            await ensure_symbol_cached(symbol, bus, config)
            cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
            if not cached or len(cached) < 20:
                return None
            closes = np.array([float(r["close"]) for r in cached])
            highs = np.array([float(r["high"]) for r in cached])
            vols = np.array([float(r["volume"]) for r in cached])
            if check_fn(closes, highs, vols, **default_params):
                stock_name = await get_stock_name(symbol, bus)
                return {
                    "symbol": symbol, "name": stock_name, "price": round(float(closes[-1]), 2),
                    "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else 0,
                    "vol_ratio": round(vols[-1] / np.mean(vols[:-1]), 2) if len(vols) > 1 and np.mean(vols[:-1]) > 0 else 1,
                }
        except Exception:
            pass
        return None

    raw_results = await asyncio.gather(*[_check_symbol(s) for s in stock_pool])
    results = [r for r in raw_results if r is not None]
    results.sort(key=lambda x: -x["vol_ratio"])

    return {"strategy": strategy_name, "matched": len(results), "results": results[:20]}

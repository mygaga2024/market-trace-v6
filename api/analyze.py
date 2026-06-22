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

        # 纸上交易: 根据决策自动执行模拟交易
        if result.get("decision") and bus:
            try:
                from core.paper_trader import get_paper_manager
                pm = get_paper_manager(bus)
                dec = result["decision"]
                await pm.execute_signal(
                    symbol, dec["action"], result["price"],
                    confidence=dec.get("confidence", 0.5),
                    reason=f"AI诊股: {dec.get('reasoning', '')[:100]}"
                )
                result["paper_trade"] = pm.get_or_create_account().get_summary()
            except Exception as e:
                logger.warning("纸上交易执行失败: {}", e)

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
                # Fallback: rough strategy check using live price data (cache unavailable)
                from services.prefetch import fetch_stock_price_via_sina
                stock_name, live_price, live_change = await fetch_stock_price_via_sina(symbol)
                if not live_price or live_change is None:
                    return None
                # Rough thresholds matching the scanner's stage-1 logic
                rough_ok = False
                if strategy == "breakout" and live_change > 1 and live_price > 5: rough_ok = True
                elif strategy == "oversold" and live_change < -3: rough_ok = True
                elif strategy == "strength" and live_change > 2: rough_ok = True
                elif strategy == "risk" and live_change < -5: rough_ok = True
                elif strategy == "ma_golden_cross" and live_change > 0.5: rough_ok = True
                elif strategy == "volume_breakout" and live_change > 3: rough_ok = True
                elif strategy == "rsi_reversal" and live_change < -2: rough_ok = True
                if not rough_ok:
                    return None
                name = stock_name or await get_stock_name(symbol, bus)
                return {
                    "symbol": symbol, "name": name, "price": round(live_price, 2),
                    "change_pct": round(live_change, 2),
                    "vol_ratio": 1.0,
                }
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


@router.get("/paper/account")
async def paper_account(request: Request):
    """纸上交易账户摘要"""
    bus = request.app.state.bus
    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from core.paper_trader import get_paper_manager
        pm = get_paper_manager(bus)
        return pm.get_or_create_account().get_summary()
    except Exception as e:
        logger.error("纸上账户查询失败: {}", e)
        return JSONResponse({"error": "获取纸上账户失败"}, status_code=500)


@router.post("/paper/mtm")
async def paper_mark_to_market(request: Request):
    """按市价估值所有纸上持仓"""
    bus = request.app.state.bus
    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from core.paper_trader import get_paper_manager
        pm = get_paper_manager(bus)
        account = pm.get_or_create_account()
        prices = {}
        for sym in list(account.positions.keys()):
            try:
                from services.prefetch import fetch_stock_price_via_sina
                _, price, _ = await fetch_stock_price_via_sina(sym)
                if price:
                    prices[sym] = price
            except Exception:
                pass
        await pm.mark_to_market(prices)
        return account.get_summary()
    except Exception as e:
        logger.error("市价估值失败: {}", e)
        return JSONResponse({"error": "市价估值失败"}, status_code=500)


@router.post("/scan/smart")
async def smart_scan_market(request: Request, limit: int = 30):
    """智能扫描: 全市场×7策略综合评分"""
    bus = request.app.state.bus
    config = request.app.state.config
    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from services.scanner import smart_scan
        result = await smart_scan(bus, config, limit=limit)
        return result
    except Exception as e:
        logger.error("智能扫描失败: {}", e)
        return JSONResponse({"error": "智能扫描执行失败"}, status_code=500)


@router.post("/scan/{strategy}")
async def scan_market(request: Request, strategy: str = "breakout", limit: int = 50):
    """全市场快速扫描: 按策略筛选全部A股"""
    bus = request.app.state.bus
    config = request.app.state.config
    if not bus:
        return JSONResponse({"error": "消息总线未就绪"}, status_code=503)
    try:
        from services.scanner import quick_scan
        result = await quick_scan(strategy, limit=limit, bus=bus)
        return result
    except Exception as e:
        logger.error("全市场扫描失败: {}", e)
        return JSONResponse({"error": "扫描执行失败"}, status_code=500)

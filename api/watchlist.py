"""
Market Trace V6.0 — 持仓列表路由
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger

from api.deps import verify_token
from services.prefetch import get_stock_name, fetch_stock_price_via_sina

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(verify_token)])

_SINA_SEM = asyncio.Semaphore(3)


@router.get("")
async def get_watchlist(request: Request):
    """获取全部持仓列表"""
    db = request.app.state.db
    bus = request.app.state.bus
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        items = await db.get_watchlist()
        entries: list[dict] = []
        for item in items:
            name = item.name or ""
            if not name and bus:
                name = await get_stock_name(item.symbol, bus)
            entries.append({
                "symbol": item.symbol,
                "name": name,
                "notes": item.notes or "",
                "added_at": item.added_at.isoformat() if item.added_at else None,
                "price": None,
                "change_pct": None,
            })

        if entries:
            async def _fetch_live(entry: dict):
                async with _SINA_SEM:
                    try:
                        # Use Tencent quote for consistency with diagnosis endpoint
                        from services.prefetch import fetch_stock_price_tencent
                        live_name, live_price, live_change = await fetch_stock_price_tencent(entry["symbol"])
                        if not live_name:
                            live_name, live_price, live_change = await fetch_stock_price_via_sina(entry["symbol"])
                        if live_name:
                            entry["name"] = live_name
                        if live_price is not None:
                            entry["price"] = live_price
                            entry["change_pct"] = live_change
                    except Exception:
                        pass

            await asyncio.gather(*[_fetch_live(e) for e in entries], return_exceptions=True)

        for entry in entries:
            if entry["price"] is not None:
                continue
            if not bus:
                continue
            try:
                cached = await bus.cache_get(f"market:raw:{entry['symbol']}")
                if cached and len(cached) >= 2:
                    c = [float(r["close"]) for r in cached]
                    entry["price"] = round(c[-1], 2)
                    entry["change_pct"] = round((c[-1] - c[-2]) / c[-2] * 100, 2)
            except Exception:
                pass

        return {"count": len(entries), "items": entries}
    except Exception as e:
        logger.error("获取持仓列表失败: {}", e)
        return JSONResponse({"error": "获取持仓列表失败"}, status_code=500)


@router.post("")
async def add_to_watchlist(request: Request):
    """添加股票到持仓列表"""
    db = request.app.state.db
    bus = request.app.state.bus
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        import json
        body = await request.body()
        data = json.loads(body) if body else {}
        symbol = str(data.get("symbol", "")).strip()
        if not symbol:
            return JSONResponse({"error": "请提供股票代码"}, status_code=400)

        name = str(data.get("name", "")).strip()
        if not name and bus:
            name = await get_stock_name(symbol, bus)
        notes = str(data.get("notes", "")).strip()

        item = await db.add_to_watchlist(symbol, name=name, notes=notes)
        return {
            "symbol": item.symbol,
            "name": item.name or "",
            "notes": item.notes or "",
            "added_at": item.added_at.isoformat() if item.added_at else None,
        }
    except Exception as e:
        logger.error("添加持仓失败: {}", e)
        return JSONResponse({"error": "添加持仓失败"}, status_code=500)


@router.delete("/{symbol}")
async def remove_from_watchlist(request: Request, symbol: str):
    """从持仓列表移除股票"""
    db = request.app.state.db
    if not db:
        return JSONResponse({"error": "数据库未就绪"}, status_code=503)
    try:
        removed = await db.remove_from_watchlist(symbol)
        if not removed:
            return JSONResponse({"error": f"股票 {symbol} 不在持仓列表中"}, status_code=404)
        return {"symbol": symbol, "removed": True}
    except Exception as e:
        logger.error("移除持仓失败: {}", e)
        return JSONResponse({"error": "移除持仓失败"}, status_code=500)

"""
Market Trace V6.0 — K线数据与仪表盘路由
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from loguru import logger

from api.deps import SESSION_COOKIE_NAME, SESSION_TOKEN, verify_token
from services.analyzer import build_kline_json, render_kline_svg

router = APIRouter(tags=["kline"])

# 仪表盘模板缓存（开发模式下每次重新读取）
_DASHBOARD_TEMPLATE: Optional[str] = None
_DASHBOARD_MTIME: float = 0.0


def _get_dashboard_html() -> str:
    global _DASHBOARD_TEMPLATE, _DASHBOARD_MTIME
    template_path = Path("templates/dashboard.html")
    if not template_path.exists():
        return "<html><body><h1>模板文件未找到</h1></body></html>"
    mtime = template_path.stat().st_mtime
    # API_TOKEN 环境变量总是从 env 读取
    dev_mode = os.environ.get("MT6_DEV", "").lower() in ("1", "true", "yes")
    if dev_mode or _DASHBOARD_TEMPLATE is None or mtime != _DASHBOARD_MTIME:
        _DASHBOARD_TEMPLATE = template_path.read_text(encoding="utf-8")
        _DASHBOARD_MTIME = mtime
    return _DASHBOARD_TEMPLATE.replace("{{API_TOKEN}}", "")


@router.get("/api/kline/{symbol}", dependencies=[Depends(verify_token)])
async def api_kline(request: Request, symbol: str):
    """K线 OHLCV JSON 数据，供前端图表渲染"""
    bus = request.app.state.bus
    cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
    if not cached or len(cached) < 5:
        return {"symbol": symbol, "bars": [], "count": 0}
    return build_kline_json(cached, symbol)


@router.get("/kline/{symbol}.svg", dependencies=[Depends(verify_token)])
async def kline_svg(request: Request, symbol: str):
    """K线 SVG 迷你图"""
    bus = request.app.state.bus
    cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
    if not cached or len(cached) < 5:
        return Response('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="20"><text x="0" y="14" font-size="12" fill="#8b949e">数据不足</text></svg>', media_type="image/svg+xml")
    closes = [float(r["close"]) for r in cached[-30:]]
    return Response(render_kline_svg(closes), media_type="image/svg+xml")


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """仪表盘首页"""
    import os
    _API_TOKEN = os.environ.get("API_TOKEN", "")
    html = _get_dashboard_html()
    response = HTMLResponse(content=html)
    if _API_TOKEN:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=SESSION_TOKEN,
            httponly=True,
            samesite="strict",
            max_age=86400,
            path="/",
        )
    return response

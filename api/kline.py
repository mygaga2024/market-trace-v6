"""
Market Trace V6.0 — K线数据与仪表盘路由
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi import HTTPException
from loguru import logger

from api.deps import SESSION_COOKIE_NAME, SESSION_TOKEN, _API_TOKEN, verify_token
from services.analyzer import build_kline_json, render_kline_svg

router = APIRouter(tags=["kline"])

# 仪表盘模板缓存（开发模式下每次重新读取）
_DASHBOARD_TEMPLATE: Optional[str] = None
_DASHBOARD_MTIME: float = 0.0

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>登录 — Market Trace</title>
<style>
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#0d1117;color:#c9d1d9;
display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:32px;width:340px}
h2{margin:0 0 20px;font-size:18px}
label{display:block;font-size:13px;margin-bottom:6px;color:#8b949e}
input{width:100%;box-sizing:border-box;padding:10px;margin-bottom:16px;border:1px solid #30363d;
border-radius:6px;background:#0d1117;color:#c9d1d9}
button{width:100%;padding:10px;border:0;border-radius:6px;background:#238636;color:#fff;cursor:pointer;font-size:14px}
button:hover{background:#2ea043}
.err{color:#f85149;font-size:13px;margin-bottom:12px;display:none}
</style>
</head>
<body>
<div class="card">
<h2>🔐 Market Trace 登录</h2>
<form id="f">
<label for="t">API Token（环境变量 API_TOKEN 的值）</label>
<input id="t" type="password" autocomplete="current-password" required>
<button type="submit">登录</button>
<div class="err" id="err">API Token 无效</div>
</form>
</div>
<script>
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  var token = document.getElementById('t').value;
  fetch('/login', {method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token: token})})
  .then(function(r){ if(r.ok){ location.href='/'; } else { document.getElementById('err').style.display='block'; } })
  .catch(function(){ document.getElementById('err').style.display='block'; });
});
</script>
</body>
</html>
"""


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
async def dashboard(request: Request):
    """仪表盘首页（公开页面；仅对已认证请求发放 session cookie）"""
    html = _get_dashboard_html()
    response = HTMLResponse(content=html)
    if _API_TOKEN:
        # 仅对已通过认证的请求发放/刷新 cookie，防止公开页面自动授予认证（S2 修复）
        authed = (
            request.cookies.get(SESSION_COOKIE_NAME, "") == SESSION_TOKEN
            or request.headers.get("authorization", "") == f"Bearer {_API_TOKEN}"
        )
        if authed:
            response.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=SESSION_TOKEN,
                httponly=True,
                samesite="strict",
                secure=os.environ.get("MT6_HTTPS", "").lower() in ("1", "true", "yes"),
                max_age=86400,
                path="/",
            )
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页：输入 API_TOKEN 换取 session cookie"""
    if not _API_TOKEN:
        return HTMLResponse("<html><body style='font-family:sans-serif;padding:40px'><h3>未配置 API_TOKEN，无需登录</h3><a href='/'>返回仪表盘</a></body></html>")
    return HTMLResponse(_LOGIN_HTML)


@router.post("/login")
async def login(request: Request):
    """校验 API_TOKEN，成功后发放 session cookie"""
    if not _API_TOKEN:
        return JSONResponse({"ok": True, "redirect": "/"})
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = str(body.get("token", "")).strip()
    if not secrets.compare_digest(token, _API_TOKEN):
        raise HTTPException(401, "API Token 无效")
    response = JSONResponse({"ok": True, "redirect": "/"})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=SESSION_TOKEN,
        httponly=True,
        samesite="strict",
        secure=os.environ.get("MT6_HTTPS", "").lower() in ("1", "true", "yes"),
        max_age=86400,
        path="/",
    )
    return response

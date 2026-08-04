"""
Market Trace V6.0 — 登录认证测试（S2 安全修复验证）

验证:
- 未认证访问仪表盘不再自动发放 session cookie
- /login 登录流程：错误 token 401，正确 token 发放 session cookie
- verify_token：无凭证 401，正确 Bearer 放行
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import api.deps
import api.kline
from api.deps import SESSION_COOKIE_NAME, verify_token

API_TOKEN = "test-api-token-123"
SESSION = "test-session-token-abc"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    """所有测试都在配置了 API_TOKEN 的环境下运行"""
    # api.deps 内 verify_token 读模块级 _API_TOKEN；api.kline 是 import 时值副本，需分别 patch
    monkeypatch.setattr(api.deps, "_API_TOKEN", API_TOKEN)
    monkeypatch.setattr(api.deps, "SESSION_TOKEN", SESSION)
    monkeypatch.setattr(api.kline, "_API_TOKEN", API_TOKEN)
    monkeypatch.setattr(api.kline, "SESSION_TOKEN", SESSION)
    yield


@pytest_asyncio.fixture
async def client():
    from main import app

    original_overrides = app.dependency_overrides
    app.dependency_overrides = {}

    mock_bus = MagicMock()
    mock_bus.health_check = AsyncMock(return_value=True)
    mock_bus.close = AsyncMock()

    import main as main_mod

    app.state.bus = mock_bus
    app.state.db = None
    app.state.start_time = time.time()
    app.state.config = main_mod.CONFIG
    app.state.agent_tasks = []

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides = original_overrides
        app.state.bus = None
        app.state.db = None
        app.state.config = None
        app.state.agent_tasks = []


# ─────────────────────────────────────────────
# verify_token 依赖
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_token_rejects_anonymous():
    """无任何凭证 → 401"""
    with pytest.raises(HTTPException) as exc:
        await verify_token(None, authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_token_accepts_bearer():
    """正确 Bearer token → 放行"""
    result = await verify_token(None, authorization=f"Bearer {API_TOKEN}")
    assert result is None


@pytest.mark.asyncio
async def test_verify_token_rejects_wrong_bearer():
    """错误 Bearer token → 403"""
    with pytest.raises(HTTPException) as exc:
        await verify_token(None, authorization="Bearer wrong-token")
    assert exc.value.status_code == 403


# ─────────────────────────────────────────────
# dashboard 不再自动发放 cookie
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_no_cookie_when_anonymous(client):
    """未认证访问 / 不应获得 session cookie（S2 核心修复）"""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_dashboard_refreshes_cookie_with_bearer(client):
    """带正确 Bearer 访问 / 可刷新 session cookie"""
    resp = await client.get("/", headers={"Authorization": f"Bearer {API_TOKEN}"})
    assert resp.status_code == 200
    assert "set-cookie" in resp.headers
    assert SESSION_COOKIE_NAME in resp.headers["set-cookie"]


# ─────────────────────────────────────────────
# /login 登录流程
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_page_renders(client):
    """GET /login 返回登录表单页"""
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "登录" in resp.text
    assert "API Token" in resp.text


@pytest.mark.asyncio
async def test_login_wrong_token_rejected(client):
    """错误 token → 401，不发放 cookie"""
    resp = await client.post("/login", json={"token": "wrong"})
    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_login_success_sets_cookie(client):
    """正确 token → 200 + session cookie"""
    resp = await client.post("/login", json={"token": API_TOKEN})
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert SESSION in set_cookie


@pytest.mark.asyncio
async def test_login_cookie_grants_access(client):
    """登录获得的 cookie 可访问受保护端点（/health/detail 无 db 依赖）"""
    login_resp = await client.post("/login", json={"token": API_TOKEN})
    cookie = login_resp.headers.get("set-cookie", "").split(";")[0]
    resp = await client.get("/health/detail", headers={"Cookie": cookie})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_protected_endpoint_401_without_auth(client):
    """未认证访问受保护端点 → 401"""
    resp = await client.get("/health/detail")
    assert resp.status_code == 401


# ─────────────────────────────────────────────
# 占位符 API_TOKEN 归一化（1.3.1 修复）
# ─────────────────────────────────────────────

def test_normalize_api_token_placeholder_is_empty():
    """占位符（your- 开头）→ 视为未配置"""
    from api.deps import _normalize_api_token
    assert _normalize_api_token("your-random-api-token") == ""
    assert _normalize_api_token("your-anything") == ""


def test_normalize_api_token_keeps_real_and_empty():
    """真实 token 保留；空串/空白 → 空"""
    from api.deps import _normalize_api_token
    assert _normalize_api_token("s3cr3t-token") == "s3cr3t-token"
    assert _normalize_api_token("") == ""
    assert _normalize_api_token("   ") == ""
    assert _normalize_api_token(None) == ""


@pytest.mark.asyncio
async def test_verify_token_skipped_when_placeholder(monkeypatch):
    """占位符被视为未配置 → 匿名请求直接放行，不再 401（认证假死修复）"""
    from api.deps import verify_token
    monkeypatch.setattr(api.deps, "_API_TOKEN", "")
    result = await verify_token(None, authorization=None)
    assert result is None


# ─────────────────────────────────────────────
# 登录/登出入口（1.3.2 新增）
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_renders_login_link_when_anonymous(client):
    """认证启用 + 未登录 → 页面渲染「登录」入口"""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "auth-btn" in resp.text
    assert "登录" in resp.text
    assert "href=\"/login\"" in resp.text
    assert "登出" not in resp.text


@pytest.mark.asyncio
async def test_dashboard_renders_logout_button_when_authed(client):
    """认证启用 + 已登录(cookie) → 页面渲染「登出」按钮"""
    login_resp = await client.post("/login", json={"token": API_TOKEN})
    cookie = login_resp.headers.get("set-cookie", "").split(";")[0]
    resp = await client.get("/", headers={"Cookie": cookie})
    assert resp.status_code == 200
    assert "登出" in resp.text
    assert "window._DS.logout()" in resp.text
    assert 'href="/login"' not in resp.text


@pytest.mark.asyncio
async def test_logout_clears_session_cookie(client):
    """POST /logout → 清除 session cookie"""
    login_resp = await client.post("/login", json={"token": API_TOKEN})
    cookie = login_resp.headers.get("set-cookie", "").split(";")[0]
    resp = await client.post("/logout", headers={"Cookie": cookie})
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "max-age=0" in set_cookie.lower() or "deleted" in set_cookie.lower() or "expires" in set_cookie.lower()


@pytest.mark.asyncio
async def test_dashboard_hides_auth_btn_when_auth_disabled(client, monkeypatch):
    """认证未启用（占位符归一化后为空）→ 页面不渲染登录/登出入口"""
    monkeypatch.setattr(api.kline, "_API_TOKEN", "")
    monkeypatch.setattr(api.kline, "SESSION_TOKEN", "")
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "auth-btn" not in resp.text
    assert "{{AUTH_STATE}}" not in resp.text

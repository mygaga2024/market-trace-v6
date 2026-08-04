"""
Market Trace V6.0 — Web API 集成测试
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from db.database import Database

TEST_DB_URL = "sqlite+aiosqlite:///data/test_web.db"


@pytest_asyncio.fixture
async def db():
    db = Database(TEST_DB_URL, echo=False)
    await db.init()

    await db.save_report("macro", "mr1", summary="RAI=0.6", data={"rai": 0.6}, confidence=0.5, symbol="000001")
    await db.save_report("signal", "sr1", summary="看多信号", data={"rsi": 55}, confidence=0.6, symbol="000001")
    await db.save_report("trace", "tr1", summary="大单流入", data={"direction": "bullish"}, confidence=0.7, symbol="000001")
    await db.save_decision("d1", "BUY", 0.75, reasoning="共振买入", evidence_sources=["macro", "signal"], provider_label="deepseek:chat")
    await db.save_decision("d2", "SELL", 0.6, reasoning="风控否决", evidence_sources=["risk"], risk_override={"reason": "止损"})

    await db.save_case("c1", features=[1.0, 0.5], decision_action="BUY", outcome=0.05)
    await db.save_case("c2", features=[0.5, 0.8], decision_action="SELL", outcome=-0.02)

    yield db
    await db.close()
    if os.path.exists("data/test_web.db"):
        os.remove("data/test_web.db")


@pytest_asyncio.fixture
async def client(db):
    from main import app
    app.dependency_overrides = {}

    from unittest.mock import MagicMock, AsyncMock
    mock_bus = MagicMock()
    mock_bus.health_check = AsyncMock(return_value=True)
    mock_bus.check_all_heartbeats = AsyncMock(return_value={
        "macro": True, "signal": True, "trace": True, "risk": True, "chief": True,
    })
    mock_bus.close = AsyncMock()

    import main as main_mod
    app.state.bus = mock_bus
    app.state.db = db
    app.state.start_time = __import__('time').time()
    app.state.config = main_mod.CONFIG
    app.state.agent_tasks = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.state.bus = None
    app.state.db = None
    app.state.config = None
    app.state.agent_tasks = []


@pytest.mark.asyncio
async def test_watchlist_add_invalid_json_400(client):
    """watchlist 添加接口对非法 JSON 请求体应返回 400 而非 500（P2 修复）"""
    resp = await client.post("/watchlist", content="{not-valid-json")
    assert resp.status_code == 400
    assert "JSON" in resp.json().get("error", "")


@pytest.mark.asyncio
async def test_health_ok(client):
    """公开端点仅返回精简状态"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.3.5"
    # 精简端点不再暴露 redis/database/agents 等内部细节
    assert "redis" not in data
    assert "agents" not in data


@pytest.mark.asyncio
async def test_health_detail(client):
    """认证端点返回完整健康信息"""
    response = await client.get("/health/detail")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["redis"] == "connected"
    assert data["database"] == "connected"
    assert data["version"] == "1.3.5"


@pytest.mark.asyncio
async def test_status_data(client):
    response = await client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "uptime_seconds" in data
    stats = data.get("decision_stats", {})
    assert stats.get("total", 0) == 2


@pytest.mark.asyncio
async def test_get_reports_macro(client):
    response = await client.get("/reports/macro")
    assert response.status_code == 200
    data = response.json()
    assert data["agent"] == "macro"
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_get_reports_signal(client):
    response = await client.get("/reports/signal")
    assert response.status_code == 200
    data = response.json()
    assert data["agent"] == "signal"


@pytest.mark.asyncio
async def test_get_reports_invalid_agent(client):
    response = await client.get("/reports/unknown")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_reports_pagination(client):
    response = await client.get("/reports/trace?limit=5&offset=0")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_latest_report(client):
    response = await client.get("/reports/macro/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["agent"] == "macro"
    assert "rai" in str(data["data"])


@pytest.mark.asyncio
async def test_get_latest_report_not_found(client):
    response = await client.get("/reports/chief/latest")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_decisions(client):
    response = await client.get("/decisions")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["stats"]["total"] == 2


@pytest.mark.asyncio
async def test_get_decision_by_id(client):
    response = await client.get("/decisions/d1")
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "BUY"
    assert data["evidence_chain"] is not None


@pytest.mark.asyncio
async def test_get_decision_not_found(client):
    response = await client.get("/decisions/nonexistent")
    assert response.status_code == 404

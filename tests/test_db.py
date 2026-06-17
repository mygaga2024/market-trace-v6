"""
Market Trace V6.0 — 数据库持久化单元测试
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from db.database import Database
from db.models import AgentReportModel, DecisionModel, SimilarCaseModel

TEST_DB_URL = "sqlite+aiosqlite:///data/test_market_trace.db"


@pytest_asyncio.fixture
async def db():
    db = Database(TEST_DB_URL, echo=False)
    await db.init()
    yield db
    await db.close()
    if os.path.exists("data/test_market_trace.db"):
        os.remove("data/test_market_trace.db")


# ---- Agent Reports ----

@pytest.mark.asyncio
async def test_save_report(db):
    report = await db.save_report(
        agent="macro",
        report_id="report_001",
        summary="RAI=0.55 温和乐观",
        data={"risk_appetite_index": 0.55},
        confidence=0.6,
        symbol="000001",
    )
    assert report.agent == "macro"
    assert report.symbol == "000001"
    assert report.confidence == 0.6


@pytest.mark.asyncio
async def test_save_report_update_existing(db):
    await db.save_report(agent="signal", report_id="sig_001", summary="原始", data={}, confidence=0.3)
    updated = await db.save_report(agent="signal", report_id="sig_001", summary="更新", data={}, confidence=0.9)
    assert updated.summary == "更新"
    assert updated.confidence == 0.9


@pytest.mark.asyncio
async def test_get_latest_report(db):
    await db.save_report(agent="macro", report_id="r1", summary="旧的", confidence=0.2)
    await db.save_report(agent="macro", report_id="r2", summary="新的", confidence=0.8)
    latest = await db.get_latest_report("macro")
    assert latest is not None
    assert latest.summary == "新的"


@pytest.mark.asyncio
async def test_get_latest_report_by_symbol(db):
    await db.save_report(agent="signal", report_id="s1", symbol="000001", summary="标的1", confidence=0.5)
    await db.save_report(agent="signal", report_id="s2", symbol="000002", summary="标的2", confidence=0.6)
    result = await db.get_latest_report("signal", symbol="000001")
    assert result is not None
    assert result.symbol == "000001"


@pytest.mark.asyncio
async def test_get_latest_report_not_found(db):
    result = await db.get_latest_report("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_reports_pagination(db):
    for i in range(5):
        await db.save_report(agent="trace", report_id=f"t{i}", summary=f"报告{i}", confidence=0.5)
    reports = await db.get_reports(agent="trace", limit=3, offset=0)
    assert len(reports) == 3


# ---- Decisions ----

@pytest.mark.asyncio
async def test_save_decision(db):
    decision = await db.save_decision(
        decision_id="dec_001",
        action="BUY",
        confidence=0.75,
        reasoning="多维度共振",
        evidence_sources=["macro", "signal", "trace"],
        evidence_chain={"macro_report_id": "r1"},
        provider_label="deepseek:deepseek-chat",
        provider_status="healthy",
    )
    assert decision.action == "BUY"
    assert decision.confidence == 0.75
    assert decision.evidence_sources == ["macro", "signal", "trace"]


@pytest.mark.asyncio
async def test_get_latest_decision(db):
    await db.save_decision("d1", "HOLD", 0.3, "旧的")
    await db.save_decision("d2", "SELL", 0.9, "新的")
    latest = await db.get_latest_decision()
    assert latest is not None
    assert latest.action == "SELL"


@pytest.mark.asyncio
async def test_get_decision_stats(db):
    await db.save_decision("d1", "BUY", 0.8)
    await db.save_decision("d2", "SELL", 0.7)
    await db.save_decision("d3", "BUY", 0.9)
    stats = await db.get_decision_stats()
    assert stats["total"] == 3
    assert stats["action_distribution"]["BUY"] == 2


@pytest.mark.asyncio
async def test_get_decision_stats_empty(db):
    stats = await db.get_decision_stats()
    assert stats["total"] == 0


# ---- Similar Cases ----

@pytest.mark.asyncio
async def test_save_case(db):
    case = await db.save_case(
        case_id="case_001",
        features=[1.0, 0.5, 0.2],
        decision_action="BUY",
        outcome=0.05,
        similarity_score=0.85,
        market_context={"rai": 0.6},
    )
    assert case.case_id == "case_001"
    assert case.outcome == 0.05


@pytest.mark.asyncio
async def test_get_cases(db):
    for i in range(3):
        await db.save_case(case_id=f"c{i}", features=[float(i), 0.5], outcome=float(i) * 0.01)
    cases = await db.get_cases(limit=10)
    assert len(cases) == 3


@pytest.mark.asyncio
async def test_get_case_statistics(db):
    await db.save_case("c1", features=[1.0], outcome=0.05)
    await db.save_case("c2", features=[0.5], outcome=-0.02)
    await db.save_case("c3", features=[0.8], outcome=0.03)
    stats = await db.get_case_statistics()
    assert stats["total"] == 3
    assert stats["avg_outcome"] is not None
    assert stats["win_rate"] >= 0


# ---- File cleanup ----

def test_cleanup():
    import os
    db_dir = "data"
    test_file = os.path.join(db_dir, "test_market_trace.db")
    if os.path.exists(test_file):
        os.remove(test_file)
    assert not os.path.exists(test_file)

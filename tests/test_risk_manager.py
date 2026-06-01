"""
Market Trace V6.0 — 风控闭环管理器单元测试
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.risk_manager import RiskManager


@pytest.fixture
def mock_bus():
    store: dict[str, dict] = {}

    async def cache_get(key):
        return store.get(key)

    async def cache_set(key, value, ttl=None):
        store[key] = value
        return True

    bus = MagicMock()
    bus.cache_get = cache_get
    bus.cache_set = cache_set
    return bus


@pytest.fixture
def rm(mock_bus):
    config = {
        "risk_manager": {
            "elevated_threshold": 3,
            "critical_threshold": 5,
            "cooldown_minutes": 60,
            "max_override_history": 100,
            "adaptive_params_enabled": True,
        }
    }
    return RiskManager(mock_bus, config)


class TestRiskManager:
    @pytest.mark.asyncio
    async def test_initial_state_normal(self, rm):
        state = await rm.get_risk_state()
        assert state["level"] == "normal"
        assert state["daily_overrides"] == 0
        assert state["total_overrides"] == 0

    @pytest.mark.asyncio
    async def test_warning_override_recorded(self, rm):
        await rm.record_override("测试警告", "REDUCE_CONFIDENCE", "warning", "000001")
        state = await rm.get_risk_state()
        assert state["daily_overrides"] == 1
        assert state["total_overrides"] == 1
        assert state["level"] == "normal"

    @pytest.mark.asyncio
    async def test_level_elevated_after_threshold(self, rm):
        for i in range(3):
            await rm.record_override(f"警告{i}", "REDUCE_CONFIDENCE", "warning", "000001")
        state = await rm.get_risk_state()
        assert state["level"] == "elevated"
        assert state["daily_overrides"] == 3

    @pytest.mark.asyncio
    async def test_level_critical_after_critical_override(self, rm):
        await rm.record_override("熔断", "FORCE_SELL", "critical", "000001")
        state = await rm.get_risk_state()
        assert state["level"] == "critical"
        assert state["current_circuit_breaker"] == "daily_drop"

    @pytest.mark.asyncio
    async def test_level_critical_after_many_warnings(self, rm):
        for i in range(5):
            await rm.record_override(f"警告{i}", "REDUCE_CONFIDENCE", "warning", "000001")
        state = await rm.get_risk_state()
        assert state["level"] == "critical"
        assert state["current_circuit_breaker"] == "override_count"

    @pytest.mark.asyncio
    async def test_override_history(self, rm):
        await rm.record_override("事件1", "REDUCE_CONFIDENCE", "warning", "000001")
        await rm.record_override("事件2", "FORCE_SELL", "critical", "600519")

        history = await rm.get_override_history()
        assert len(history) == 2
        assert history[0]["reason"] == "事件2"
        assert history[1]["reason"] == "事件1"

    @pytest.mark.asyncio
    async def test_position_risk_multiplier_normal(self, rm):
        suggestion = await rm.get_position_suggestion(
            "000001", capital=100000, price=10.0, method="kelly",
            win_prob=0.6, avg_win=0.04, avg_loss=0.02,
        )
        assert suggestion["risk_level"] == "normal"
        assert suggestion["risk_multiplier"] == 1.0
        assert suggestion["position_pct"] > 0

    @pytest.mark.asyncio
    async def test_position_risk_multiplier_critical(self, rm):
        await rm.record_override("熔断", "FORCE_SELL", "critical", "000001")

        suggestion = await rm.get_position_suggestion(
            "000001", capital=100000, price=10.0, method="kelly",
            win_prob=0.6, avg_win=0.04, avg_loss=0.02,
        )
        assert suggestion["risk_level"] == "critical"
        assert suggestion["risk_multiplier"] == 0.25
        assert suggestion["warning"] != ""

    @pytest.mark.asyncio
    async def test_clear_daily_counters(self, rm):
        for _ in range(4):
            await rm.record_override("警告", "REDUCE_CONFIDENCE", "warning", "000001")
        assert (await rm.get_risk_state())["daily_overrides"] == 4

        await rm.clear_daily_counters()
        assert (await rm.get_risk_state())["daily_overrides"] == 0

    @pytest.mark.asyncio
    async def test_no_bus_returns_defaults(self):
        rm_no_bus = RiskManager(None, {})
        state = await rm_no_bus.get_risk_state()
        assert state["level"] == "normal"
        history = await rm_no_bus.get_override_history()
        assert history == []

    @pytest.mark.asyncio
    async def test_equal_weight_position(self, rm):
        suggestion = await rm.get_position_suggestion(
            "000001", capital=100000, price=20.0, method="equal",
            num_stocks=5,
        )
        assert suggestion["method"] == "equal"
        assert suggestion["position_pct"] <= 0.25

    @pytest.mark.asyncio
    async def test_parity_position(self, rm):
        suggestion = await rm.get_position_suggestion(
            "000001", capital=100000, price=10.0, method="parity",
            volatilities=[0.2, 0.3, 0.25],
        )
        assert suggestion["method"] == "parity"
        assert suggestion["risk_multiplier"] == 1.0

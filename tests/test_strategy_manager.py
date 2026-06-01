"""
Market Trace V6.0 — 策略生命周期管理器单元测试
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backtest.strategy_manager import StrategyManager


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
def sm(mock_bus):
    return StrategyManager(
        mock_bus,
        consecutive_loss_threshold=3,
        min_win_rate=0.35,
        min_score=-1.0,
        min_total_trades=3,
    )


class TestStrategyManager:
    @pytest.mark.asyncio
    async def test_all_strategies_active_initially(self, sm):
        all_s = await sm.get_all_strategies()
        assert len(all_s) == 7
        for name, info in all_s.items():
            assert info["status"] == "active"
            assert info["consecutive_losses"] == 0

    @pytest.mark.asyncio
    async def test_get_active_strategies(self, sm):
        active = await sm.get_active_strategies()
        assert len(active) == 7
        assert "breakout" in active

    @pytest.mark.asyncio
    async def test_disable_and_enable(self, sm):
        await sm.disable_strategy("breakout", "测试禁用")
        active = await sm.get_active_strategies()
        assert "breakout" not in active

        await sm.enable_strategy("breakout")
        active = await sm.get_active_strategies()
        assert "breakout" in active

    @pytest.mark.asyncio
    async def test_consecutive_loss_reset_on_healthy(self, sm):
        good_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": 1.5,
                    "max_drawdown_pct": 10, "win_rate_pct": 60,
                    "total_trades": 10, "total_return_pct": 20,
                    "profit_factor": 2.0, "score": 2.5,
                }
            }
        }
        await sm.evaluate_health(good_results)
        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["consecutive_losses"] == 0

    @pytest.mark.asyncio
    async def test_consecutive_loss_increment(self, sm):
        bad_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": -1.0,
                    "max_drawdown_pct": 30, "win_rate_pct": 20,
                    "total_trades": 5, "total_return_pct": -15,
                    "profit_factor": 0.5, "score": -2.0,
                }
            }
        }
        await sm.evaluate_health(bad_results)
        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["consecutive_losses"] == 1

    @pytest.mark.asyncio
    async def test_auto_disable_after_threshold(self, sm):
        bad_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": -1.0,
                    "max_drawdown_pct": 30, "win_rate_pct": 20,
                    "total_trades": 5, "total_return_pct": -15,
                    "profit_factor": 0.5, "score": -2.0,
                }
            }
        }
        for _ in range(3):
            await sm.evaluate_health(bad_results)

        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_healthy_results_dont_disable(self, sm):
        good_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": 1.5,
                    "max_drawdown_pct": 10, "win_rate_pct": 60,
                    "total_trades": 10, "total_return_pct": 20,
                    "profit_factor": 2.0, "score": 2.5,
                }
            }
        }
        for _ in range(5):
            await sm.evaluate_health(good_results)

        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["status"] == "active"
        assert all_s["breakout"]["consecutive_losses"] == 0

    @pytest.mark.asyncio
    async def test_recovery_resets_counter(self, sm):
        bad_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": -1.0,
                    "max_drawdown_pct": 30, "win_rate_pct": 20,
                    "total_trades": 5, "total_return_pct": -15,
                    "profit_factor": 0.5, "score": -2.0,
                }
            }
        }
        good_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": 1.5,
                    "max_drawdown_pct": 10, "win_rate_pct": 60,
                    "total_trades": 10, "total_return_pct": 20,
                    "profit_factor": 2.0, "score": 2.5,
                }
            }
        }
        await sm.evaluate_health(bad_results)
        await sm.evaluate_health(bad_results)
        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["consecutive_losses"] == 2

        await sm.evaluate_health(good_results)
        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["consecutive_losses"] == 0

    @pytest.mark.asyncio
    async def test_already_disabled_skipped(self, sm):
        bad_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": -1.0,
                    "max_drawdown_pct": 30, "win_rate_pct": 20,
                    "total_trades": 5, "total_return_pct": -15,
                    "profit_factor": 0.5, "score": -2.0,
                }
            }
        }
        for _ in range(3):
            await sm.evaluate_health(bad_results)
        assert (await sm.get_all_strategies())["breakout"]["status"] == "disabled"

        await sm.evaluate_health(bad_results)
        assert (await sm.get_all_strategies())["breakout"]["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_no_bus_fallback_to_active(self):
        sm_no_bus = StrategyManager(None)
        active = await sm_no_bus.get_active_strategies()
        assert len(active) == 7
        all_s = await sm_no_bus.get_all_strategies()
        for info in all_s.values():
            assert info["status"] == "active"

    @pytest.mark.asyncio
    async def test_multi_symbol_aggregate(self, sm):
        multi_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": 2.0,
                    "max_drawdown_pct": 5, "win_rate_pct": 70,
                    "total_trades": 8, "total_return_pct": 25,
                    "profit_factor": 3.0, "score": 3.0,
                }
            },
            "600519": {
                "breakout": {
                    "label": "强势突破", "sharpe": -1.0,
                    "max_drawdown_pct": 20, "win_rate_pct": 30,
                    "total_trades": 4, "total_return_pct": -10,
                    "profit_factor": 0.8, "score": -1.0,
                }
            }
        }
        changes = await sm.evaluate_health(multi_results)
        all_s = await sm.get_all_strategies()
        assert all_s["breakout"]["consecutive_losses"] == 0
        assert changes.get("breakout") == "reset" or changes.get("breakout") is None

    @pytest.mark.asyncio
    async def test_returns_changes_dict(self, sm):
        bad_results = {
            "000001": {
                "breakout": {
                    "label": "强势突破", "sharpe": -1.0,
                    "max_drawdown_pct": 30, "win_rate_pct": 20,
                    "total_trades": 5, "total_return_pct": -15,
                    "profit_factor": 0.5, "score": -2.0,
                }
            }
        }
        changes = await sm.evaluate_health(bad_results)
        assert "breakout" in changes
        assert changes["breakout"] == "consecutive_loss_1"

"""
Market Trace V6.0 — 回测引擎单元测试
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from core.bus import MessageBus
from backtest.replay import MarketReplay, ReplayConfig, ReplayProgress
from backtest.runner import BacktestRunner, BacktestResult, Trade


# ---- Replay Tests ----

class TestMarketReplay:
    @pytest.fixture
    def bus(self) -> MagicMock:
        bus = MagicMock(spec=MessageBus)
        bus.publish = AsyncMock(return_value=1)
        return bus

    @pytest.mark.asyncio
    async def test_replay_batch(self, bus):
        data = [
            {"timestamp": "2026-01-05T00:00:00", "close": 10.0, "open": 9.8},
            {"timestamp": "2026-01-06T00:00:00", "close": 10.5, "open": 10.1},
            {"timestamp": "2026-01-07T00:00:00", "close": 11.0, "open": 10.6},
        ]
        replay = MarketReplay(bus)
        config = ReplayConfig(symbol="000001", speed=0)
        progress = await replay.replay(config, data)

        assert progress.total == 3
        assert progress.processed == 3
        assert progress.errors == 0

    @pytest.mark.asyncio
    async def test_replay_empty_data(self, bus):
        replay = MarketReplay(bus)
        progress = await replay.replay(ReplayConfig(symbol="000001"), [])
        assert progress.total == 0

    @pytest.mark.asyncio
    async def test_replay_date_filter(self, bus):
        data = [
            {"timestamp": "2026-01-05T00:00:00", "close": 10.0},
            {"timestamp": "2026-01-10T00:00:00", "close": 10.5},
            {"timestamp": "2026-01-15T00:00:00", "close": 11.0},
        ]
        replay = MarketReplay(bus)
        config = ReplayConfig(symbol="000001", speed=0, start_date="2026-01-08")
        progress = await replay.replay(config, data)
        assert progress.processed == 2

    @pytest.mark.asyncio
    async def test_replay_max_events(self, bus):
        data = [
            {"timestamp": f"2026-01-{d:02d}T00:00:00", "close": 10.0} for d in range(1, 11)
        ]
        replay = MarketReplay(bus)
        config = ReplayConfig(symbol="000001", speed=0, max_events=5)
        progress = await replay.replay(config, data)
        assert progress.processed == 5

    def test_stop(self, bus):
        replay = MarketReplay(bus)
        replay.stop()
        assert replay._running is False


# ---- Runner Tests ----

class TestBacktestRunner:
    @pytest.fixture
    def runner(self) -> BacktestRunner:
        return BacktestRunner(initial_capital=100_000, commission_rate=0.0003, slippage=0.001)

    def test_initial_state(self, runner):
        assert runner.capital == 100_000
        assert runner.position.quantity == 0
        assert len(runner.trades) == 0

    def test_buy_execution(self, runner):
        trade = runner.execute("BUY", 10.0, confidence=0.8, reason="测试买入")

        assert trade is not None
        assert trade.action == "BUY"
        assert trade.price == pytest.approx(10.01, rel=0.01)
        assert trade.quantity > 0
        assert runner.position.quantity > 0
        assert runner.capital < 100_000

    def test_sell_execution(self, runner):
        runner.execute("BUY", 10.0, confidence=1.0)
        qty_before = runner.position.quantity

        trade = runner.execute("SELL", 11.0, reason="止盈")

        assert trade is not None
        assert trade.action == "SELL"
        assert runner.position.quantity == 0
        assert runner.capital > 0

    def test_hold_does_nothing(self, runner):
        trade = runner.execute("HOLD", 10.0)
        assert trade is None

    def test_wait_does_nothing(self, runner):
        trade = runner.execute("WAIT", 10.0)
        assert trade is None

    def test_buy_with_insufficient_capital(self, runner):
        runner.capital = 50
        trade = runner.execute("BUY", 10.0, confidence=1.0, reason="资金不足测试")
        assert trade is not None
        assert trade.quantity == 0

    def test_sell_without_position(self, runner):
        trade = runner.execute("SELL", 10.0, reason="无持仓")
        assert trade is None

    def test_reset(self, runner):
        runner.execute("BUY", 10.0, confidence=1.0)
        runner.execute("SELL", 11.0)
        assert len(runner.trades) > 0

        runner.reset()
        assert runner.capital == 100_000
        assert runner.position.quantity == 0
        assert len(runner.trades) == 0

    def test_finalize_metrics(self, runner):
        prices = np.linspace(10.0, 15.0, 20)
        for p in prices[:5]:
            runner.execute("BUY", p, confidence=0.8)

        runner.execute("SELL", prices[10], confidence=1.0)

        result = runner.finalize()

        assert isinstance(result, BacktestResult)
        assert result.initial_capital == 100_000
        assert result.final_equity > 0
        assert result.total_trades == 1
        assert -1.0 <= result.total_return <= 1.0

    def test_finalize_no_trades(self, runner):
        result = runner.finalize()
        assert result.sharpe_ratio == 0.0
        assert result.max_drawdown == 0.0
        assert result.win_rate == 0.0

    def test_profit_factor(self, runner):
        runner.execute("BUY", 10.0, confidence=1.0)
        runner.execute("SELL", 11.0)
        result = runner.finalize()
        assert result.win_rate == 1.0

    def test_to_dict(self, runner):
        runner.execute("BUY", 10.0, confidence=1.0)
        runner.execute("SELL", 11.0)
        result = runner.finalize()
        d = result.to_dict()
        assert "sharpe_ratio" in d
        assert "max_drawdown_pct" in d
        assert "win_rate_pct" in d
        assert d["total_trades"] == 1


class TestBacktestScenarios:
    """场景回测：连续盈利 vs 连续亏损"""

    def test_winning_streak(self):
        runner = BacktestRunner(initial_capital=100_000)

        for i in range(5):
            runner.execute("BUY", 10.0 + i, confidence=1.0)
            runner.execute("SELL", 10.5 + i, confidence=1.0)

        result = runner.finalize()
        assert result.win_rate == 1.0
        assert result.total_return > 0
        assert result.sharpe_ratio > 0

    def test_losing_streak(self):
        runner = BacktestRunner(initial_capital=100_000)

        for i in range(3):
            runner.execute("BUY", 10.0 + i, confidence=1.0)
            runner.execute("SELL", 9.5 + i, confidence=1.0)

        result = runner.finalize()
        assert result.win_rate == 0.0
        assert result.total_return < 0

    def test_drawdown_tracking(self):
        runner = BacktestRunner(initial_capital=100_000)

        runner.execute("BUY", 10.0, confidence=1.0)
        runner.execute("SELL", 8.0)
        runner.execute("BUY", 9.0, confidence=1.0)
        runner.execute("SELL", 12.0)

        result = runner.finalize()
        assert result.max_drawdown > 0

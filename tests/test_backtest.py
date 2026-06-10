"""
Market Trace V6.0 — 回测引擎单元测试
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from core.bus import MessageBus
from backtest.replay import MarketReplay, ReplayConfig, ReplayProgress
from backtest.runner import PortfolioRunner, BacktestResult, Trade


def _make_bar(time: str = "2026-01-05", close: float = 10.0, **kw) -> dict:
    bar = {"time": time, "open": close - 0.1, "high": close + 0.2,
            "low": close - 0.3, "close": close, "volume": 1000000}
    bar.update(kw)
    return bar


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

class TestPortfolioRunner:
    @pytest.fixture
    def runner(self) -> PortfolioRunner:
        return PortfolioRunner(initial_capital=100_000, commission_rate=0.0003, slippage=0.001)

    def test_initial_state(self, runner):
        assert runner.capital == 100_000
        assert runner.position.quantity == 0
        assert len(runner.trades) == 0

    def test_step_records_equity(self, runner):
        bar = _make_bar(close=10.0)
        snapshot = runner.step(bar)
        assert snapshot is not None
        assert snapshot["equity"] == 100_000
        assert len(runner.equity_curve) == 1

    def test_buy_execution(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        trade = runner.buy(bar, size_pct=0.8, reason="测试买入")

        assert trade is not None
        assert trade.action == "BUY"
        assert trade.quantity > 0
        assert runner.position.quantity > 0
        assert runner.capital < 100_000

    def test_sell_execution(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        runner.buy(bar, size_pct=1.0)

        bar2 = _make_bar(close=11.0, time="2026-01-06")
        runner.step(bar2)
        trade = runner.sell(bar2, reason="止盈")

        assert trade is not None
        assert trade.action == "SELL"
        assert trade.pnl > 0
        assert runner.position.quantity == 0

    def test_buy_when_holding_does_nothing(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        runner.buy(bar, size_pct=1.0)

        bar2 = _make_bar(close=10.5, time="2026-01-06")
        runner.step(bar2)
        trade = runner.buy(bar2, size_pct=0.5)
        assert trade is None  # already holding

    def test_sell_without_position(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        trade = runner.sell(bar, reason="无持仓")
        assert trade is None

    def test_reset(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        runner.buy(bar, size_pct=1.0)
        runner.sell(_make_bar(close=11.0, time="2026-01-06"))

        runner.reset()
        assert runner.capital == 100_000
        assert runner.position.quantity == 0
        assert len(runner.trades) == 0

    def test_finalize_metrics(self, runner):
        runner.step(_make_bar(close=10.0, time="2026-01-05"))
        runner.buy(_make_bar(close=10.0, time="2026-01-05"), size_pct=1.0)
        runner.step(_make_bar(close=12.0, time="2026-01-10"))
        runner.sell(_make_bar(close=12.0, time="2026-01-10"), reason="卖出")

        result = runner.finalize(symbol="000001", strategy="test")

        assert isinstance(result, BacktestResult)
        assert result.symbol == "000001"
        assert result.final_equity > 100000
        assert result.total_trades == 1
        assert result.win_rate == 1.0

    def test_finalize_no_trades(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        result = runner.finalize()
        assert result.total_trades == 0
        assert result.max_drawdown >= 0

    def test_check_exits_stop_loss(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        runner.buy(bar, size_pct=1.0)

        # 价格跌到止损线以下
        bar2 = _make_bar(close=9.4, time="2026-01-06", low=9.3)
        runner.step(bar2)
        trade = runner.check_exits(bar2)
        assert trade is not None
        assert trade.action == "SELL"
        assert "止损" in trade.reason
        assert trade.pnl < 0

    def test_take_profit_and_trailing_stop(self, runner):
        # 买入价格10, 涨到12后触发止盈监控, 回落触发移动止盈
        runner.step(_make_bar(close=10.0))
        runner.buy(_make_bar(close=10.0), size_pct=1.0)

        # 涨到12 (高于 avg*1.15=11.5)
        runner.step(_make_bar(close=12.0, high=12.0, time="2026-01-06"))
        runner.check_exits(_make_bar(close=12.0, high=12.0, time="2026-01-06"))

        # 回落到11.3 (低于 highest*0.95 = 11.4)
        runner.step(_make_bar(close=11.3, low=11.3, time="2026-01-07"))
        trade = runner.check_exits(_make_bar(close=11.3, low=11.3, time="2026-01-07"))
        assert trade is not None
        assert "移动止盈" in trade.reason

    def test_benchmark_tracking(self, runner):
        for close in [10.0, 10.5, 11.0, 10.8, 12.0]:
            bar = _make_bar(close=close, time=f"2026-01-{1+len(runner.equity_curve):02d}")
            runner.step(bar)

        result = runner.finalize()
        assert len(result.benchmark_curve) == 5
        # 基准收益 (10→12)
        assert result.benchmark_return > 0.15

    def test_to_dict(self, runner):
        bar = _make_bar(close=10.0)
        runner.step(bar)
        runner.buy(bar, size_pct=1.0)
        runner.sell(_make_bar(close=11.0, time="2026-01-06"))

        result = runner.finalize(symbol="000001", strategy="test")
        d = result.to_dict()
        assert "sharpe_ratio" in d
        assert "sortino_ratio" in d
        assert "max_drawdown_pct" in d
        assert "win_rate_pct" in d
        assert "alpha" in d
        assert "beta" in d
        assert "equity_curve" in d
        assert "drawdown_curve" in d
        assert "trade_markers" in d
        assert d["total_trades"] == 1


class TestBacktestScenarios:
    def test_winning_streak(self):
        runner = PortfolioRunner(initial_capital=100_000)
        for i in range(5):
            bar = _make_bar(close=10.0 + i, time=f"2026-01-{i*2+5:02d}")
            runner.step(bar)
            runner.buy(bar, size_pct=1.0)
            bar2 = _make_bar(close=10.5 + i, time=f"2026-01-{i*2+6:02d}")
            runner.step(bar2)
            runner.sell(bar2, reason="卖出")

        result = runner.finalize()
        assert result.win_rate == 1.0
        assert result.total_return > 0
        assert result.max_consecutive_wins == 5

    def test_losing_streak(self):
        runner = PortfolioRunner(initial_capital=100_000)
        for i in range(3):
            bar = _make_bar(close=10.0 + i, time=f"2026-01-{i*2+5:02d}")
            runner.step(bar)
            runner.buy(bar, size_pct=1.0)
            bar2 = _make_bar(close=9.5 + i, time=f"2026-01-{i*2+6:02d}")
            runner.step(bar2)
            runner.sell(bar2, reason="卖出")

        result = runner.finalize()
        assert result.win_rate == 0.0
        assert result.total_return < 0
        assert result.max_consecutive_losses == 3

    def test_drawdown_tracking(self, runner=None):
        runner = PortfolioRunner(initial_capital=100_000)
        bar = _make_bar(close=10.0)
        runner.step(bar)
        runner.buy(bar, size_pct=1.0)
        runner.sell(_make_bar(close=8.0, time="2026-01-06"))

        bar2 = _make_bar(close=9.0, time="2026-01-07")
        runner.step(bar2)
        runner.buy(bar2, size_pct=1.0)
        runner.sell(_make_bar(close=12.0, time="2026-01-08"))

        result = runner.finalize()
        assert result.max_drawdown > 0
        assert len(result.equity_curve) > 0

"""
Market Trace V6.0 — 纸上交易模块单元测试
覆盖: 买入/卖出执行、资金不足拒绝、序列化/反序列化、mark_to_market 估值
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.paper_trader import (
    PaperAccount,
    PaperOrder,
    PaperPosition,
    PaperTradeManager,
)


# ── PaperPosition Tests ──


class TestPaperPosition:
    def test_initial_state(self):
        pos = PaperPosition(symbol="000001")
        assert pos.quantity == 0
        assert pos.avg_cost == 0.0
        assert pos.cost_basis == 0.0
        assert pos.entry_time is None

    def test_add_first_buy(self):
        pos = PaperPosition(symbol="000001")
        ts = datetime.now(timezone.utc)
        pos.add(100, 10.0, ts)
        assert pos.quantity == 100
        assert pos.avg_cost == 10.0
        assert pos.cost_basis == 1000.0
        assert pos.entry_time == ts

    def test_add_averaging_up(self):
        """加仓后均价应正确计算"""
        pos = PaperPosition(symbol="000001")
        ts = datetime.now(timezone.utc)
        pos.add(100, 10.0, ts)
        pos.add(100, 12.0, ts)
        assert pos.quantity == 200
        assert pos.avg_cost == pytest.approx(11.0)  # (1000+1200)/200

    def test_reduce_partial(self):
        pos = PaperPosition(symbol="000001")
        pos.add(200, 10.0, datetime.now(timezone.utc))
        pos.reduce(100)
        assert pos.quantity == 100
        assert pos.avg_cost == 10.0  # avg_cost 不变

    def test_reduce_all(self):
        pos = PaperPosition(symbol="000001")
        pos.add(100, 10.0, datetime.now(timezone.utc))
        pos.reduce(100)
        assert pos.quantity == 0
        assert pos.avg_cost == 0.0
        assert pos.entry_time is None

    def test_reduce_more_than_held(self):
        pos = PaperPosition(symbol="000001")
        pos.add(50, 10.0, datetime.now(timezone.utc))
        pos.reduce(100)
        assert pos.quantity == 0

    def test_unrealized_pnl_profit(self):
        pos = PaperPosition(symbol="000001")
        pos.add(100, 10.0, datetime.now(timezone.utc))
        assert pos.unrealized_pnl(12.0) == pytest.approx(200.0)
        assert pos.unrealized_pnl_pct(12.0) == pytest.approx(0.2)

    def test_unrealized_pnl_loss(self):
        pos = PaperPosition(symbol="000001")
        pos.add(100, 10.0, datetime.now(timezone.utc))
        assert pos.unrealized_pnl(8.0) == pytest.approx(-200.0)

    def test_unrealized_pnl_zero_cost(self):
        pos = PaperPosition(symbol="000001")
        assert pos.unrealized_pnl_pct(10.0) == 0.0

    def test_market_value(self):
        pos = PaperPosition(symbol="000001")
        pos.add(100, 10.0, datetime.now(timezone.utc))
        assert pos.market_value(15.0) == pytest.approx(1500.0)

    def test_commission_tracking(self):
        pos = PaperPosition(symbol="000001")
        pos.add(100, 10.0, datetime.now(timezone.utc), commission=3.0)
        pos.add(100, 12.0, datetime.now(timezone.utc), commission=3.6)
        assert pos.total_commission == pytest.approx(6.6)


# ── PaperAccount Tests ──


class TestPaperAccount:
    def _make_account(self, capital=100_000):
        return PaperAccount(account_id="test", initial_capital=capital, capital=capital)

    def test_initial_equity(self):
        acct = self._make_account()
        assert acct.total_equity == 100_000
        assert acct.total_pnl == 0.0
        assert acct.total_pnl_pct == 0.0

    def test_can_buy_within_budget(self):
        acct = self._make_account()
        assert acct.can_buy(10.0, 100) is True

    def test_can_buy_exceeds_95pct(self):
        """买入金额+佣金不得超过可用资金的95%"""
        acct = self._make_account(capital=1000)
        # 1000 * 0.95 = 950, 需 10*100 + 佣金 = 1000.3 > 950
        assert acct.can_buy(10.0, 100) is False

    def test_execute_buy(self):
        acct = self._make_account()
        order = acct.execute_buy("000001", 10.0, 100, reason="test buy")
        assert order is not None
        assert order.action == "BUY"
        assert order.quantity == 100
        assert order.price == 10.0
        assert "000001" in acct.positions
        assert acct.capital < 100_000  # 扣减了

    def test_execute_buy_zero_quantity(self):
        acct = self._make_account()
        assert acct.execute_buy("000001", 10.0, 0) is None

    def test_execute_buy_insufficient_funds(self):
        acct = self._make_account(capital=100)
        assert acct.execute_buy("000001", 10.0, 100) is None

    def test_execute_sell(self):
        acct = self._make_account()
        acct.execute_buy("000001", 10.0, 100)
        order = acct.execute_sell("000001", 12.0, reason="take profit")
        assert order is not None
        assert order.action == "SELL"
        assert order.quantity == 100
        assert "000001" not in acct.positions  # 全部卖出

    def test_execute_sell_partial(self):
        acct = self._make_account()
        acct.execute_buy("000001", 10.0, 200)
        order = acct.execute_sell("000001", 12.0, quantity=100)
        assert order.quantity == 100
        assert acct.positions["000001"].quantity == 100

    def test_execute_sell_no_position(self):
        acct = self._make_account()
        assert acct.execute_sell("000001", 10.0) is None

    def test_execute_sell_excess_quantity(self):
        """卖出数量超过持仓时，应自动修正为持仓量"""
        acct = self._make_account()
        acct.execute_buy("000001", 10.0, 100)
        order = acct.execute_sell("000001", 12.0, quantity=500)
        assert order.quantity == 100

    def test_pnl_after_round_trip(self):
        """买入后以更高价卖出，总P&L应为正"""
        acct = self._make_account()
        acct.execute_buy("000001", 10.0, 100)
        acct.execute_sell("000001", 12.0)
        # 净盈利 = (12-10)*100 - 佣金
        assert acct.total_pnl > 0

    def test_get_summary(self):
        acct = self._make_account()
        acct.execute_buy("000001", 10.0, 100, reason="test")
        summary = acct.get_summary()
        assert summary["account_id"] == "test"
        assert summary["position_count"] == 1
        assert summary["total_orders"] == 1
        assert len(summary["positions"]) == 1
        assert len(summary["recent_orders"]) == 1

    def test_order_id_unique(self):
        """连续买入两只股票，order_id 应不同"""
        acct = self._make_account()
        o1 = acct.execute_buy("000001", 10.0, 100)
        o2 = acct.execute_buy("000002", 20.0, 100)
        assert o1.order_id != o2.order_id

    def test_commission_deducted(self):
        acct = self._make_account()
        acct.execute_buy("000001", 100.0, 100)
        # 成本 = 100*100 = 10000, 佣金 = 10000*0.0003 = 3
        expected_capital = 100_000 - 10_000 - 3
        assert acct.capital == pytest.approx(expected_capital)


# ── PaperTradeManager Tests ──


class TestPaperTradeManager:
    def _make_manager(self):
        bus = MagicMock()
        # Mock _PERSIST_PATH to avoid reading/writing real files
        with patch.object(PaperTradeManager, '_PERSIST_PATH', Path("/tmp/test_paper_acct.json")):
            mgr = PaperTradeManager(bus)
        return mgr

    def test_get_or_create_account(self):
        mgr = self._make_manager()
        acct = mgr.get_or_create_account("test1", initial_capital=50_000)
        assert acct.account_id == "test1"
        assert acct.capital == 50_000

    def test_get_existing_account(self):
        mgr = self._make_manager()
        acct1 = mgr.get_or_create_account("test2")
        acct2 = mgr.get_or_create_account("test2")
        assert acct1 is acct2

    @pytest.mark.asyncio
    async def test_execute_signal_buy(self):
        mgr = self._make_manager()
        order = await mgr.execute_signal(
            "000001", "BUY", 10.0, confidence=0.8, reason="test"
        )
        assert order is not None
        assert order.action == "BUY"

    @pytest.mark.asyncio
    async def test_execute_signal_hold(self):
        mgr = self._make_manager()
        result = await mgr.execute_signal("000001", "HOLD", 10.0, reason="观望")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_signal_wait(self):
        mgr = self._make_manager()
        result = await mgr.execute_signal("000001", "WAIT", 10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_signal_sell_no_position(self):
        mgr = self._make_manager()
        result = await mgr.execute_signal("000001", "SELL", 10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_signal_sell_with_position(self):
        mgr = self._make_manager()
        await mgr.execute_signal("000001", "BUY", 10.0, confidence=0.8)
        order = await mgr.execute_signal("000001", "SELL", 12.0)
        assert order is not None
        assert order.action == "SELL"

    @pytest.mark.asyncio
    async def test_high_price_single_share(self):
        """高价股允许单股买入"""
        mgr = self._make_manager()
        order = await mgr.execute_signal(
            "600519", "BUY", 1800.0, confidence=0.8
        )
        assert order is not None
        assert order.quantity >= 1

    @pytest.mark.asyncio
    async def test_mark_to_market(self):
        mgr = self._make_manager()
        await mgr.execute_signal("000001", "BUY", 10.0, confidence=0.8)
        await mgr.mark_to_market({"000001": 12.0})
        acct = mgr.get_or_create_account("default")
        assert len(acct.equity_history) == 1
        assert acct.equity_history[0]["equity"] > 0

    @pytest.mark.asyncio
    async def test_get_summary_nonexistent(self):
        mgr = self._make_manager()
        summary = await mgr.get_summary("nonexistent")
        assert "error" in summary


# ── Serialization Tests ──


class TestPaperTraderPersistence:
    def test_save_and_load(self, tmp_path):
        """测试序列化/反序列化完整性"""
        persist_path = tmp_path / "paper_accounts.json"

        bus = MagicMock()
        with patch.object(PaperTradeManager, '_PERSIST_PATH', persist_path):
            mgr = PaperTradeManager(bus)
            acct = mgr.get_or_create_account("test", initial_capital=50_000)
            acct.execute_buy("000001", 10.0, 100, reason="test buy")
            acct.execute_buy("000002", 20.0, 200, reason="test buy 2")
            acct.execute_sell("000001", 12.0, reason="profit")
            mgr._save_to_disk()

            assert persist_path.exists()

        # 重新加载
        with patch.object(PaperTradeManager, '_PERSIST_PATH', persist_path):
            mgr2 = PaperTradeManager(bus)
            acct2 = mgr2._accounts.get("test")
            assert acct2 is not None
            assert acct2.initial_capital == 50_000
            assert "000002" in acct2.positions
            assert acct2.positions["000002"].quantity == 200
            assert len(acct2.orders) >= 2  # 至少有 buy + sell

    def test_load_empty_file(self, tmp_path):
        """空文件不应崩溃"""
        persist_path = tmp_path / "paper_accounts.json"
        persist_path.write_text("{}")
        bus = MagicMock()
        with patch.object(PaperTradeManager, '_PERSIST_PATH', persist_path):
            mgr = PaperTradeManager(bus)
            assert len(mgr._accounts) == 0

    def test_load_corrupt_file(self, tmp_path):
        """损坏文件不应崩溃"""
        persist_path = tmp_path / "paper_accounts.json"
        persist_path.write_text("not json{{{")
        bus = MagicMock()
        with patch.object(PaperTradeManager, '_PERSIST_PATH', persist_path):
            mgr = PaperTradeManager(bus)
            assert len(mgr._accounts) == 0

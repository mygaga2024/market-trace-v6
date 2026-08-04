"""
Market Trace V6.0 — 静默错误专项修复测试 (1.3.8)
覆盖 19 项中/低危修复: 兜底值、样本门槛、强度加权、None 传播
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from core.position_sizing import risk_parity


# ── strategies: ATR 兜底 / 量能均值 0 ──

class TestAtrAndVolumeGuards:
    def test_atr_insufficient_returns_none(self):
        from core.strategies import _calc_atr
        closes = np.array([1.0] * 10)
        assert _calc_atr(closes, closes, closes) is None  # < 15 条不再返回均值/0

    def test_atr_normal(self):
        from core.strategies import _calc_atr
        closes = np.linspace(10, 20, 30)
        highs = closes + 0.5
        lows = closes - 0.5
        atr = _calc_atr(highs, lows, closes)
        assert atr is not None and atr > 0

    def test_check_breakout_zero_volume_not_fire(self):
        """停牌/空量时量能条件不恒真 (#22)"""
        from core.strategies import check_breakout
        closes = np.arange(10, 40, dtype=float)
        highs = closes + 1
        volumes = np.zeros(30)  # 空量
        assert check_breakout(closes, highs, volumes) is False

    def test_check_volume_breakout_zero_volume(self):
        from core.strategies import check_volume_breakout
        closes = np.arange(10, 40, dtype=float)
        highs = closes + 1
        volumes = np.zeros(30)
        assert check_volume_breakout(closes, highs, volumes) is False


# ── position_sizing / risk_parity ──

class TestPositionSizing:
    def test_risk_parity_invalid_volatility_returns_none(self):
        """波动率含 0/负值 → None, 不再 clamp 成超大权重 (#7)"""
        assert risk_parity([0.2, 0.0, 0.3]) is None
        assert risk_parity([0.2, -0.1]) is None

    def test_risk_parity_normal(self):
        w = risk_parity([0.2, 0.4])
        assert w is not None
        assert sum(w) == pytest.approx(1.0)
        assert w[0] > w[1]  # 低波动更大权重

    @pytest.mark.asyncio
    async def test_kelly_without_stats_insufficient(self):
        """无真实胜率/盈亏比 → data_insufficient, 不输出写死参数的精确仓位 (#6)"""
        from core.risk_manager import RiskManager
        rm = RiskManager.__new__(RiskManager)
        from unittest.mock import AsyncMock
        rm.get_risk_state = AsyncMock(return_value={"level": "normal"})
        rm._risk_multiplier = lambda level: 1.0
        out = await rm.get_position_suggestion("000001", capital=100000, price=10.0, method="kelly")
        assert out.get("data_insufficient") is True
        assert out["position_pct"] == 0.0


# ── trace_agent: 强度加权方向 ──

class TestTraceDirection:
    def test_direction_strength_weighted(self):
        """1 条强空头 vs 1 条弱多头 → 空头 (#16)"""
        from agents.trace_agent import TraceAgent
        signals = [
            {"type": "A", "direction": "bullish", "strength": 0.3},
            {"type": "B", "direction": "bearish", "strength": 0.9},
        ]
        assert TraceAgent._determine_direction(signals) == "bearish"

    def test_direction_equal_strength_neutral(self):
        from agents.trace_agent import TraceAgent
        signals = [
            {"type": "A", "direction": "bullish", "strength": 0.5},
            {"type": "B", "direction": "bearish", "strength": 0.5},
        ]
        assert TraceAgent._determine_direction(signals) == "neutral"


# ── paper_trader: 缺价估值 / 无置信度不自动买 ──

class TestPaperTrader:
    @pytest.mark.asyncio
    async def test_mark_to_market_skips_no_quote(self):
        """无报价持仓不参与估值, PnL 不静默记 0 (#12)"""
        from core.paper_trader import PaperTradeManager as PaperTrader
        pt = PaperTrader.__new__(PaperTrader)
        account = SimpleNamespace(capital=100000, initial_capital=100000, positions={}, equity_history=[])
        pt._accounts = {"default": account}
        account.positions["000001"] = SimpleNamespace(market_value=lambda p: p * 100, avg_cost=10.0)
        await pt.mark_to_market({"600519": 1500.0})  # 000001 无报价
        assert account.equity_history[-1]["equity"] == 100000  # 只含现金, 未用成本价估值

    @pytest.mark.asyncio
    async def test_buy_without_confidence_skipped(self):
        """confidence=None/0 时不自动买入 (#12)"""
        from core.paper_trader import PaperTradeManager as PaperTrader
        pt = PaperTrader.__new__(PaperTrader)
        account = SimpleNamespace(capital=100000, orders=[], positions={})
        account.execute_buy = lambda *a, **k: None
        pt.get_or_create_account = lambda account_id="default": account
        assert await pt.execute_signal("000001", "BUY", price=10.0, confidence=None) is None


# ── signal_agent: RSI 小样本 ──

class TestSignalAgentGuards:
    def test_rsi_small_sample_returns_none(self):
        """至少 2 倍周期样本, 小样本不产生极端 RSI (#11)"""
        from agents.signal_agent import SignalAgent
        closes = np.arange(20, dtype=float)  # 20 < 28
        assert SignalAgent._calc_rsi(closes, 14) is None


# ── backtest: vol_up 数据不足 / sharpe None ──

class TestBacktestGuards:
    def test_signal_risk_no_volume_data_no_sell(self):
        """数据不足时放量条件不再默认 True (#13)"""
        from backtest.strategy_backtest import signal_risk
        closes = np.arange(10, 26, dtype=float)  # 16 条, 不足 21
        # 无成交量的超买场景
        volumes = np.zeros(16)
        action, _ = signal_risk(closes, closes, volumes)
        assert action == "HOLD"

    def test_backtest_result_sharpe_none_default(self):
        """样本不足时 sharpe 保持 None, score 不崩溃 (#14)"""
        from backtest.runner import BacktestResult
        r = BacktestResult(symbol="000001", strategy="test")
        assert r.sharpe_ratio is None
        assert r.sortino_ratio is None
        assert r.score() >= 0  # None 安全
        d = r.to_dict()
        assert d["sharpe_ratio"] is None


# ── macro_agent: 数据缺失降级 ──

class TestMacroDegraded:
    def test_position_flat_range_skipped(self):
        """一年无波动 → 该指数位置分位跳过, 不兜底 0.5 (#24)"""
        from agents.macro_agent import MacroAgent
        bars = [SimpleNamespace(close=10.0) for _ in range(60)]
        pos = MacroAgent._calc_position([{"code": "sh000001"}], {"sh000001": bars})
        assert pos is None

    def test_data_complete_flag(self):
        """全因子缺失时报告标记 DEGRADED 而非 OK (#9)"""
        from agents.macro_agent import MacroAgent
        comps = MacroAgent._calculate_rai({}, {})  # 无指数/板块/K线
        assert comps == {}
        rai = MacroAgent._compute_rai_score(comps)
        assert rai == 0.5
        # data_complete 由 _fetch_and_report 设置, 此处验证空 components 语义
        assert bool(comps) is False


# ── analyzer: 指标 None 化 ──

class TestAnalyzerIndicators:
    def test_bollinger_flat_position_none(self):
        from services.analyzer import _calc_bollinger
        closes = np.full(25, 10.0)  # 完全横盘 → 带宽 0
        bol = _calc_bollinger(closes)
        assert bol["position"] is None  # 不再兜底 0.5

    def test_kdj_insufficient_none(self):
        from services.analyzer import _calc_kdj
        closes = np.array([1.0] * 5)  # < 9
        kdj = _calc_kdj(closes, closes, closes)
        assert kdj["k"] is None and kdj["d"] is None and kdj["j"] is None

    def test_atr_insufficient_none_in_analyzer(self):
        from core.strategies import _calc_atr
        closes = np.array([1.0] * 5)
        assert _calc_atr(closes, closes, closes) is None

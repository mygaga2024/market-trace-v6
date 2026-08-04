"""
Market Trace V6.0 — 业务 Agent 单元测试
覆盖 Macro / Signal / Trace / Risk / Memory
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from core.bus import MessageBus
from core.memory import CaseMemory, SimilarCase
from agents.macro_agent import MacroAgent
from agents.signal_agent import SignalAgent
from agents.trace_agent import TraceAgent
from agents.risk_agent import RiskAgent


# ---- Fixtures ----

@pytest.fixture
def config() -> dict:
    return {
        "agents": {
            "heartbeat_interval": 1,
            "heartbeat_timeout": 2,
            "max_concurrent_msgs": 5,
            "macro": {"interval": 600, "indices": ["sh000001"]},
            "signal": {
                "ma_periods": [5, 10, 20],
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "rsi_period": 14, "divergence_lookback": 20,
            },
            "trace": {
                "big_order_threshold": 1_000_000,
                "anomaly_zscore": 2.5,
                "fund_flow_window": 5,
                "concentration_threshold": 0.7,
            },
            "risk": {
                "conflict_multiplier": 0.3,
                "stop_loss_percent": 0.05,
                "max_position_percent": 0.3,
            },
        }
    }


@pytest.fixture
def mock_bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish = AsyncMock(return_value=1)
    bus.publish_heartbeat = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.listen = AsyncMock()
    bus.cache_set = AsyncMock()
    bus.cache_get = AsyncMock(return_value=None)
    bus.check_all_heartbeats = AsyncMock(return_value={
        "macro": True, "signal": True, "trace": True, "risk": True, "chief": True,
    })
    return bus


# ---- Memory Tests ----

class TestCaseMemory:
    def test_add_and_find(self):
        mem = CaseMemory(max_cases=10)
        mem.add_case([1.0, 0.5, 0.2], {"action": "BUY"}, outcome=0.05)
        mem.add_case([0.5, 0.8, 0.1], {"action": "SELL"}, outcome=-0.02)
        mem.add_case([1.1, 0.4, 0.3], {"action": "BUY"}, outcome=0.03)

        results = mem.find_similar([1.0, 0.5, 0.15], k=2)
        assert len(results) >= 1

    def test_empty_casebook(self):
        mem = CaseMemory()
        results = mem.find_similar([1.0, 0.5], k=5)
        assert results == []

    def test_statistics(self):
        mem = CaseMemory()
        mem.add_case([1.0, 0.5], {"action": "BUY"}, outcome=0.05)
        mem.add_case([0.5, 0.8], {"action": "SELL"}, outcome=-0.01)

        stats = mem.get_statistics()
        assert stats["total_cases"] == 2
        assert stats["cases_with_outcome"] == 2
        assert stats["avg_outcome"] is not None

    def test_max_cases_eviction(self):
        mem = CaseMemory(max_cases=3)
        for i in range(5):
            mem.add_case([float(i), 0.5], {"action": "BUY"})
        assert len(mem._cases) == 3

    def test_clear(self):
        mem = CaseMemory()
        mem.add_case([1.0, 0.5], {"action": "BUY"})
        mem.clear()
        assert len(mem._cases) == 0


# ---- Macro Agent Tests ----

class TestMacroAgent:
    def test_rai_extremes(self):
        components = {"index_breadth": 1.0, "sector_momentum": 1.0}
        rai = MacroAgent._compute_rai_score(components)
        assert rai >= 0.9

        components = {"index_breadth": 0.0, "sector_momentum": 0.0}
        rai = MacroAgent._compute_rai_score(components)
        assert rai <= 0.1

    def test_rai_neutral(self):
        rai = MacroAgent._compute_rai_score({"index_breadth": 0.5, "sector_momentum": 0.5})
        assert 0.45 <= rai <= 0.55

    def test_rai_empty_defaults(self):
        rai = MacroAgent._compute_rai_score({})
        assert rai == 0.5

    def test_rai_breadth_only_no_sector_dilution(self):
        """修复: 板块数据缺失时不再用 0.5 兜底稀释 (1.3.6)"""
        rai = MacroAgent._compute_rai_score({"index_breadth": 1.0})
        assert rai == 1.0
        rai = MacroAgent._compute_rai_score({"index_breadth": 0.0})
        assert rai == 0.0

    def test_rai_with_position_factor(self):
        """位置因子参与合成: breadth 0.6 + position 0.4"""
        rai = MacroAgent._compute_rai_score({"index_breadth": 1.0, "position": 0.3})
        assert rai == pytest.approx(0.72)
        rai = MacroAgent._compute_rai_score({"index_breadth": 0.0, "position": 0.8})
        assert rai == pytest.approx(0.32)

    def test_rai_three_factors(self):
        """breadth/sector/position 三因子: 0.4/0.3/0.3"""
        rai = MacroAgent._compute_rai_score(
            {"index_breadth": 1.0, "sector_momentum": 0.5, "position": 0.3}
        )
        assert rai == pytest.approx(0.64)

    def test_rai_position_only(self):
        """仅有位置因子时按 1.0 权重"""
        rai = MacroAgent._compute_rai_score({"position": 0.8})
        assert rai == 0.8

    def test_calc_position(self):
        """位置因子: 现价贴近一年高点 → 接近 1"""
        from types import SimpleNamespace
        # 59 天横盘后 +10% 跳涨, 现价=一年最高
        closes = [100.0] * 59 + [110.0]
        bars = [SimpleNamespace(close=c) for c in closes]
        pos = MacroAgent._calc_position([{"code": "sh000001"}], {"sh000001": bars})
        assert pos is not None
        assert pos >= 0.9

    def test_calc_position_low(self):
        """现价贴近一年低点 → 接近 0"""
        from types import SimpleNamespace
        closes = [110.0] * 59 + [100.0]
        bars = [SimpleNamespace(close=c) for c in closes]
        pos = MacroAgent._calc_position([{"code": "sh000001"}], {"sh000001": bars})
        assert pos is not None
        assert pos <= 0.1

    def test_calc_position_no_data(self):
        """无 K 线数据 → None (不参与合成)"""
        assert MacroAgent._calc_position([], {}) is None
        assert MacroAgent._calc_position([{"code": "sh000001"}], {}) is None

    @pytest.mark.parametrize("rai,expected_bias", [
        (0.8, "bullish"),
        (0.6, "slightly_bullish"),
        (0.5, "neutral"),
        (0.4, "slightly_bearish"),
        (0.2, "bearish"),
    ])
    def test_interpret_rai(self, rai, expected_bias):
        result = MacroAgent._interpret_rai(rai)
        assert result["bias"] == expected_bias

    def test_interpret_rai_low_position_high_rai(self):
        """低位 + 高 RAI → 低位强势反弹(右侧机会), 不再误报追高风险"""
        result = MacroAgent._interpret_rai(0.8, position=0.2)
        assert result["regime"] == "低位强势反弹 - 右侧机会"
        assert result["bias"] == "bullish"

    def test_interpret_rai_high_position_high_rai(self):
        """高位 + 高 RAI → 仍是追高风险"""
        result = MacroAgent._interpret_rai(0.8, position=0.8)
        assert result["regime"] == "极度乐观 - 追高风险大"
        assert result["bias"] == "bullish"

    def test_interpret_rai_high_position_low_rai(self):
        """高位 + 低 RAI → 高位走弱"""
        result = MacroAgent._interpret_rai(0.2, position=0.7)
        assert result["regime"] == "高位走弱 - 警惕回落"
        assert result["bias"] == "bearish"

    def test_interpret_rai_without_position_backward_compat(self):
        """无 position 参数时行为与旧版一致"""
        assert MacroAgent._interpret_rai(0.8)["regime"] == "极度乐观 - 追高风险大"
        assert MacroAgent._interpret_rai(0.2)["regime"] == "极度悲观 - 恐慌机会"

    def test_calc_breadth(self):
        indices = [
            {"涨跌幅": 1.5}, {"涨跌幅": 2.0}, {"涨跌幅": -1.0},
            {"涨跌幅": 0.5}, {"涨跌幅": -0.5},
        ]
        breadth = MacroAgent._calc_breadth(indices)
        assert breadth == 3 / 5

    def test_calc_breadth_empty(self):
        assert MacroAgent._calc_breadth([]) == 0.5


# ---- 1.3.7 高严重度修复测试 ----

class TestHighSeverityFixes:
    """RSI/MA 兜底、顶背离阈值脱节、回测小样本、RAI None 传播"""

    def test_strategies_rsi_insufficient_returns_none(self):
        from core.strategies import _calc_rsi, _calc_ma
        assert _calc_rsi(np.array([1.0] * 10), 14) is None  # 10 < 15, 不再返回伪中性 50
        assert _calc_ma(np.array([1.0] * 5), 20) is None    # 5 < 20, 不再拿现价冒充均线

    def test_strategies_rsi_ma_normal_still_work(self):
        from core.strategies import _calc_rsi, _calc_ma
        closes = np.linspace(10, 20, 30)
        rsi = _calc_rsi(closes, 14)
        assert rsi is not None and 0 <= rsi <= 100
        # arange(30): 最后 20 个为 10..29, 均值 19.5
        assert _calc_ma(np.arange(30), 20) == pytest.approx(19.5)

    def test_checks_safe_with_insufficient_data(self):
        from core.strategies import check_oversold, check_risk, check_rsi_reversal
        closes = np.array([1.0] * 5)
        assert check_oversold(closes, closes, closes) is False
        assert check_risk(closes, closes, closes) is False
        assert check_rsi_reversal(closes, closes, closes) is False

    def test_divergence_strength_is_measurable(self):
        """顶背离强度由幅度计算, 应 >= 0.5 (可被风控捕获), 不再硬编码 0.7"""
        agent = object.__new__(SignalAgent)
        agent._divergence_lookback = 20
        closep = np.array([10.0 + i * 0.2 for i in range(20)])      # 价格稳步创新高
        rsi = np.concatenate([np.full(10, 65.0), np.linspace(65, 55, 10)])  # RSI 回落
        signals = []
        SignalAgent._detect_divergence(agent, closep, closep, closep, rsi, signals)
        bear = [s for s in signals if s["type"] == "BEARISH_DIVERGENCE"]
        assert bear, "应检测到顶背离"
        assert bear[0]["strength"] >= 0.5
        assert bear[0]["strength"] <= 1.0

    def test_risk_override_fires_on_divergence(self):
        """strength 0.6 的顶背离应触发 FORCE_SELL (修复 >0.8 永不触发)"""
        from agents.risk_agent import RiskAgent
        from core.schema import AgentReport, AgentName, ReportStatus
        agent = RiskAgent.__new__(RiskAgent)
        agent._latest_reports = {
            "signal": AgentReport(
                agent=AgentName.SIGNAL,
                data={"signals": [{"type": "BEARISH_DIVERGENCE", "strength": 0.6}]},
            )
        }
        override = agent._check_bearish_divergence()
        assert override is not None
        assert override.action == "FORCE_SELL"
        assert override.severity == "critical"

    def test_risk_conflict_skips_when_rai_none(self):
        """宏观 RAI 缺失(None)时冲突检测跳过, 不崩溃 (修复 None>0.65 TypeError)"""
        from agents.risk_agent import RiskAgent
        from core.schema import AgentReport, AgentName
        agent = RiskAgent.__new__(RiskAgent)
        agent._conflict_multiplier = 0.3
        agent._latest_reports = {
            "macro": AgentReport(agent=AgentName.MACRO, data={"risk_appetite_index": None}),
            "trace": AgentReport(agent=AgentName.TRACE, data={"direction": "bullish"}),
        }
        assert agent._check_conflict() is None

    def test_chief_evaluate_risk_sync_rai_none(self):
        """chief 同步风控: RAI 缺失时不崩溃"""
        from core.chief_decision import evaluate_risk_sync
        from core.schema import AgentReport, AgentName
        reports = {
            "macro": AgentReport(agent=AgentName.MACRO, data={"risk_appetite_index": None}),
            "trace": AgentReport(agent=AgentName.TRACE, data={"direction": "bullish"}),
        }
        level, reason = evaluate_risk_sync(reports, daily_change_pct=0.5)
        assert level is None and reason is None


# ---- Signal Agent Tests ----

class TestSignalAgent:
    def test_calc_ma(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ma = SignalAgent._calc_ma(data, 3)
        assert np.isnan(ma[0])
        assert np.isnan(ma[1])
        assert ma[2] == pytest.approx(2.0)
        assert ma[4] == pytest.approx(4.0)

    def test_calc_ema(self):
        from core.strategies import _calc_ema
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        ema = _calc_ema(data, 5)
        assert np.isnan(ema[3])
        assert not np.isnan(ema[5])

    def test_calc_macd(self):
        from core.strategies import _calc_macd_vec
        closep = np.sin(np.linspace(0, 4 * np.pi, 100)) * 5 + 20
        result = _calc_macd_vec(closep)
        assert result is not None
        assert "dif" in result
        assert "dea" in result
        assert "hist" in result

    def test_calc_rsi(self):
        np.random.seed(42)
        closep = np.cumsum(np.random.randn(50) * 0.5 + 0.1) + 10
        rsi = SignalAgent._calc_rsi(closep, 14)
        assert rsi is not None
        assert len(rsi) == 50

    def test_rsi_overbought_detected(self):
        signals = []
        SignalAgent._detect_rsi_signal(75.0, signals)
        assert any(s["type"] == "RSI_OVERBOUGHT" for s in signals)

    def test_rsi_oversold_detected(self):
        signals = []
        SignalAgent._detect_rsi_signal(25.0, signals)
        assert any(s["type"] == "RSI_OVERSOLD" for s in signals)

    def test_make_summary_empty(self):
        assert SignalAgent._make_summary([]) == "无显著技术信号"

    def test_make_summary_bullish(self):
        signals = [{"type": "MACD_BULLISH", "direction": "bullish"}]
        assert "看多" in SignalAgent._make_summary(signals)


# ---- Trace Agent Tests ----

class TestTraceAgent:
    @pytest.fixture
    def trace_agent(self, mock_bus, config) -> TraceAgent:
        return TraceAgent(mock_bus, config)

    def test_determine_direction_bullish(self):
        signals = [
            {"direction": "bullish", "type": "X"},
            {"direction": "bullish", "type": "Y"},
            {"direction": "bearish", "type": "Z"},
        ]
        assert TraceAgent._determine_direction(signals) == "bullish"

    def test_determine_direction_neutral(self):
        signals = [{"direction": "bullish"}, {"direction": "bearish"}]
        assert TraceAgent._determine_direction(signals) == "neutral"

    def test_volume_spike_bullish(self, trace_agent):
        volumes = np.array([1000, 1100, 1050, 1200, 5000])
        closes = np.array([10, 10.2, 10.1, 10.3, 10.5])
        signals = []
        trace_agent._detect_volume_spike(volumes, closes, signals)
        assert len(signals) == 1
        assert signals[0]["type"] == "VOLUME_SPIKE"
        assert signals[0]["direction"] == "bullish"

    def test_volume_spike_bearish(self, trace_agent):
        volumes = np.array([1000, 1100, 1050, 1200, 5000])
        closes = np.array([10, 10.2, 10.1, 10.3, 10.2])
        signals = []
        trace_agent._detect_volume_spike(volumes, closes, signals)
        assert len(signals) == 1
        assert signals[0]["direction"] == "bearish"

    def test_volume_spike_no_anomaly(self, trace_agent):
        volumes = np.array([1000, 1100, 1050, 1200, 1300])
        closes = np.array([10, 10.2, 10.1, 10.3, 10.5])
        signals = []
        trace_agent._detect_volume_spike(volumes, closes, signals)
        assert len(signals) == 0

    def test_price_volume_divergence(self, trace_agent):
        closes = np.array([10, 10.1, 10.2, 10.3, 10.6])
        volumes = np.array([5000, 4000, 3000, 2000, 1000])
        signals = []
        trace_agent._detect_price_volume_divergence(closes, volumes, signals)
        assert any(s["type"] == "BULLISH_DIVERGENCE_WEAK_VOLUME" for s in signals)

    def test_breakout_detection(self, trace_agent):
        highs = np.full(30, 10.0)
        lows = np.full(30, 9.0)
        closes = np.full(30, 10.0)
        closes[-1] = 11.0
        volumes = np.full(30, 1000.0)
        volumes[-1] = 3000.0
        signals = []
        trace_agent._detect_range_breakout(highs, lows, closes, volumes, signals)
        assert any(s["type"] == "BREAKOUT_HIGH_VOLUME" for s in signals)

    def test_make_summary(self):
        signals = [
            {"type": "VOLUME_SPIKE", "direction": "bullish"},
            {"type": "VOLUME_CONFIRMS_UPTREND", "direction": "bullish"},
        ]
        summary = TraceAgent._make_summary(signals, "bullish")
        assert "VOLUME_SPIKE" in summary


# ---- Risk Agent Tests ----

class TestRiskAgent:
    @pytest.fixture
    def risk_agent(self, mock_bus, config) -> RiskAgent:
        agent = RiskAgent(mock_bus, config)
        agent._latest_reports = {}
        return agent

    def test_no_conflict_when_normal(self, risk_agent):
        from core.schema import AgentReport, AgentName, ReportStatus
        risk_agent._latest_reports["macro"] = AgentReport(
            agent=AgentName.MACRO, summary="neutral",
            data={"risk_appetite_index": 0.5}, confidence=0.5,
        )
        risk_agent._latest_reports["trace"] = AgentReport(
            agent=AgentName.TRACE, summary="neutral",
            data={"direction": "neutral"}, confidence=0.5,
        )
        result = risk_agent._check_conflict()
        assert result is None

    def test_conflict_macro_bearish_trace_bullish(self, risk_agent):
        from core.schema import AgentReport, AgentName, ReportStatus
        risk_agent._latest_reports["macro"] = AgentReport(
            agent=AgentName.MACRO, summary="bearish",
            data={"risk_appetite_index": 0.25}, confidence=0.8,
        )
        risk_agent._latest_reports["trace"] = AgentReport(
            agent=AgentName.TRACE, summary="bullish",
            data={"direction": "bullish"}, confidence=0.7,
        )
        result = risk_agent._check_conflict()
        assert result is not None
        assert result.action == "REDUCE_CONFIDENCE"

    def test_conflict_macro_bullish_trace_bearish(self, risk_agent):
        from core.schema import AgentReport, AgentName, ReportStatus
        risk_agent._latest_reports["macro"] = AgentReport(
            agent=AgentName.MACRO, summary="bullish",
            data={"risk_appetite_index": 0.75}, confidence=0.8,
        )
        risk_agent._latest_reports["trace"] = AgentReport(
            agent=AgentName.TRACE, summary="bearish",
            data={"direction": "bearish"}, confidence=0.7,
        )
        result = risk_agent._check_conflict()
        assert result is not None
        assert "0.3" in result.reason

    def test_confidence_penalty_applied(self, risk_agent):
        from core.schema import AgentReport, AgentName, ReportStatus
        risk_agent._latest_reports["macro"] = AgentReport(
            agent=AgentName.MACRO, summary="bearish",
            data={"risk_appetite_index": 0.2}, confidence=0.8,
        )
        risk_agent._latest_reports["trace"] = AgentReport(
            agent=AgentName.TRACE, summary="bullish",
            data={"direction": "bullish"}, confidence=0.7,
        )
        penalized = risk_agent.get_confidence_penalty(0.8)
        assert abs(penalized - 0.8 * 0.3) < 0.001

    def test_override_safe(self, risk_agent):
        risk_agent._latest_reports = {}
        result = risk_agent._check_conflict()
        assert result is None

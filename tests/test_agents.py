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

    def test_calc_breadth(self):
        indices = [
            {"涨跌幅": 1.5}, {"涨跌幅": 2.0}, {"涨跌幅": -1.0},
            {"涨跌幅": 0.5}, {"涨跌幅": -0.5},
        ]
        breadth = MacroAgent._calc_breadth(indices)
        assert breadth == 3 / 5

    def test_calc_breadth_empty(self):
        assert MacroAgent._calc_breadth([]) == 0.5


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
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        ema = SignalAgent._calc_ema(data, 5)
        assert np.isnan(ema[3])
        assert not np.isnan(ema[5])

    def test_calc_macd(self):
        agent = SignalAgent(MagicMock(spec=MessageBus), {
            "agents": {
                "heartbeat_interval": 1, "heartbeat_timeout": 2, "max_concurrent_msgs": 5,
                "signal": {"ma_periods": [5], "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                            "rsi_period": 14, "divergence_lookback": 20},
            }
        })
        closep = np.sin(np.linspace(0, 4 * np.pi, 100)) * 5 + 20
        result = agent._calc_macd(closep)
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

    def test_make_summary(self):
        signals = [
            {"type": "BIG_ORDER_INFLOW", "direction": "bullish"},
            {"type": "FLOW_ZSCORE_ANOMALY", "direction": "bullish"},
        ]
        summary = TraceAgent._make_summary(signals, "bullish")
        assert "BIG_ORDER_INFLOW" in summary
        assert "FLOW_ZSCORE_ANOMALY" in summary

    def test_big_order_detection(self, trace_agent):
        signals = []
        trace_agent._detect_big_order("000001", 2_000_000, 1_500_000, signals)
        inflow = [s for s in signals if s["type"] == "BIG_ORDER_INFLOW"]
        super_large = [s for s in signals if s["type"] == "SUPER_LARGE_INFLOW"]
        assert len(inflow) == 1
        assert len(super_large) == 1

    def test_big_order_outflow(self, trace_agent):
        signals = []
        trace_agent._detect_big_order("000001", -2_000_000, -500_000, signals)
        outflow = [s for s in signals if s["type"] == "BIG_ORDER_OUTFLOW"]
        assert len(outflow) == 1

    def test_concentration_accumulation(self, trace_agent):
        signals = []
        trace_agent._detect_concentration_shift(800_000, 200_000, signals)
        acc = [s for s in signals if s["type"] == "CONCENTRATION_ACCUMULATION"]
        assert len(acc) == 1

    def test_concentration_distribution(self, trace_agent):
        signals = []
        trace_agent._detect_concentration_shift(-800_000, -200_000, signals)
        dist = [s for s in signals if s["type"] == "CONCENTRATION_DISTRIBUTION"]
        assert len(dist) == 1


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

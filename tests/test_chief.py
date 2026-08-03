"""
Market Trace V6.0 — LLM 回退链 + Chief Analyst 单元测试
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.bus import MessageBus
from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from core.llm_factory import (
    LLMInterface,
    OpenAICompatibleLLM,
    RuleBasedAnalyzer,
    LLMFallbackChain,
)
from core.schema import AgentReport, AgentName, Decision, DecisionAction, ProviderStatus
from agents.chief_analyst import ChiefAnalyst


CONFIG = {
    "agents": {
        "heartbeat_interval": 1, "heartbeat_timeout": 2, "max_concurrent_msgs": 5,
        "macro": {"interval": 600},
        "signal": {"ma_periods": [5], "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "rsi_period": 14, "divergence_lookback": 20},
        "trace": {"big_order_threshold": 1_000_000, "anomaly_zscore": 2.5, "fund_flow_window": 5, "concentration_threshold": 0.7},
        "risk": {"conflict_multiplier": 0.3, "stop_loss_percent": 0.05, "max_position_percent": 0.3},
    }
}


@pytest.fixture
def mock_bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish = AsyncMock(return_value=1)
    bus.publish_heartbeat = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.listen = AsyncMock()
    bus.cache_get = AsyncMock(return_value=None)
    bus.check_all_heartbeats = AsyncMock(return_value={
        "macro": True, "signal": True, "trace": True, "risk": True, "chief": True,
    })
    return bus


def make_macro_report(**kw) -> AgentReport:
    return AgentReport(
        agent=AgentName.MACRO,
        timestamp=datetime.now(timezone.utc),
        summary="RAI=0.60",
        data={"risk_appetite_index": kw.pop("rai", 0.60),
               "interpretation": {"regime": "温和乐观", "bias": "slightly_bullish"},
               "components": {"index_breadth": 0.65, "sector_momentum": 0.55},
               **kw},
        confidence=0.6,
    )


def make_signal_report(**kw) -> AgentReport:
    return AgentReport(
        agent=AgentName.SIGNAL,
        timestamp=datetime.now(timezone.utc),
        summary=kw.pop("summary", "看多信号2个"),
        data={"symbol": "000001",
               "indicators": {"macd": {"dif": 0.01, "dea": 0.005, "histogram": 0.01}, "rsi": 55.0},
               "signals": [{"type": "MACD_BULLISH", "direction": "bullish", "strength": 0.6}],
               "signal_count": 1,
               "reliability": 0.55,
               **kw},
        confidence=0.5,
    )


def make_trace_report(**kw) -> AgentReport:
    return AgentReport(
        agent=AgentName.TRACE,
        timestamp=datetime.now(timezone.utc),
        summary=kw.pop("summary", "大单流入"),
        data={"symbol": "000001",
               "fund_flow": {"main_net_inflow": 2_000_000, "main_net_inflow_pct": 0.15, "super_large_net": 1_200_000},
               "signals": [{"type": "BIG_ORDER_INFLOW", "direction": "bullish", "strength": 0.7}],
               "direction": "bullish",
               "signal_count": 1,
               **kw},
        confidence=0.7,
    )


# ---- RuleBasedAnalyzer Tests ----

class TestRuleBasedAnalyzer:
    @pytest.mark.asyncio
    async def test_bullish_scenario(self):
        analyzer = RuleBasedAnalyzer({"fallback": {"weights": {"macro": 0.25, "signal": 0.25, "trace": 0.30, "risk": 0.20}}})
        reports = {
            "macro": make_macro_report(rai=0.7),
            "signal": make_signal_report(signals=[{"type": "MACD_BULLISH", "direction": "bullish", "strength": 0.8}]),
            "trace": make_trace_report(signals=[{"type": "BIG_ORDER_INFLOW", "direction": "bullish", "strength": 0.9}]),
        }
        decision = await analyzer.analyze(reports)
        assert decision.provider_status == ProviderStatus.FALLBACK
        assert decision.provider_label == "rule_based:fallback"

    @pytest.mark.asyncio
    async def test_empty_reports(self):
        analyzer = RuleBasedAnalyzer({"fallback": {"weights": {}}})
        reports = {}
        decision = await analyzer.analyze(reports)
        assert decision.action in (DecisionAction.HOLD, DecisionAction.WAIT)
        assert decision.provider_status == ProviderStatus.FALLBACK

    @pytest.mark.asyncio
    async def test_health_check_always_true(self):
        analyzer = RuleBasedAnalyzer({})
        assert await analyzer.health_check() is True


# ---- OpenAICompatibleLLM Tests ----

class TestOpenAICompatibleLLM:
    @pytest.fixture
    def llm_config(self) -> dict:
        return {
            "model": "test-model",
            "api_key": "test-key",
            "base_url": "https://test.api.example.com/v1",
            "timeout": 10,
            "max_retries": 1,
            "temperature": 0.3,
            "max_tokens": 2048,
        }

    @pytest.fixture
    def llm(self, llm_config) -> OpenAICompatibleLLM:
        cb = CircuitBreaker(name="test-llm", failure_threshold=2, recovery_timeout=5)
        return OpenAICompatibleLLM("test", llm_config, cb)

    @pytest.mark.parametrize("raw,expected", [
        ('{"action":"BUY"}', '{"action":"BUY"}'),
        ('[{"action":"BUY"}]', '{"action":"BUY"}'),
        ('[{"a":1},{"b":2}]', '[{"a":1},{"b":2}]'),
        ('```json\n{"action":"BUY"}\n```', '{"action":"BUY"}'),
        ('```json\n[{"action":"BUY"}]\n```', '{"action":"BUY"}'),
        ('reasoning text\n{"action":"BUY"}', '{"action":"BUY"}'),
        ('["not", "a", "dict"]', '["not", "a", "dict"]'),
        ('  {"action":"BUY"}  ', '{"action":"BUY"}'),
    ])
    def test_clean_json_content(self, llm, raw, expected):
        result = llm._clean_json_content(raw)
        assert json.loads(result) == json.loads(expected)

    def test_build_prompt_contains_all_reports(self, llm):
        reports = {
            "macro": make_macro_report(rai=0.55),
            "signal": make_signal_report(),
            "trace": make_trace_report(),
        }
        prompt = llm._build_prompt(reports)
        assert "宏观报告" in prompt
        assert "技术信号报告" in prompt
        assert "资金痕迹报告" in prompt
        assert "RAI" in prompt
        assert "MACD" in prompt

    def test_build_prompt_partial_reports(self, llm):
        reports = {"macro": make_macro_report()}
        prompt = llm._build_prompt(reports)
        assert "宏观报告" in prompt
        assert "技术信号报告" not in prompt

    def test_build_prompt_macd_none_no_crash(self, llm):
        """K线不足时 MACD 值为 None，prompt 构建不应崩溃（P1-3 修复）"""
        reports = {
            "macro": make_macro_report(),
            "signal": make_signal_report(
                indicators={"macd": {"dif": None, "dea": None, "histogram": None}, "rsi": 55.0},
                signals=[], signal_count=0, reliability=0.5,
            ),
        }
        prompt = llm._build_prompt(reports)
        assert "技术信号报告" in prompt
        assert "MACD: DIF=" not in prompt

    def test_parse_decision(self, llm):
        llm_result = {
            "action": "BUY",
            "confidence": 0.75,
            "reasoning": "技术面和资金面共振，看多信号明确",
            "key_insights": ["主力大单流入明显", "MACD金叉确认"],
        }
        reports = {"macro": make_macro_report(), "signal": make_signal_report()}
        decision = llm._parse_decision(llm_result, reports)
        assert decision.action == DecisionAction.BUY
        assert decision.confidence == 0.75
        assert len(decision.evidence_sources) == 2
        assert decision.evidence_chain["key_insights"] == llm_result["key_insights"]
        assert "test:test-model" in decision.provider_label

    def test_parse_decision_invalid_action(self, llm):
        decision = llm._parse_decision({"action": "INVALID"}, {})
        assert decision.action == DecisionAction.WAIT

    @pytest.mark.asyncio
    async def test_analyze_successful_api_call(self, llm, llm_config):
        mock_response = {
            "choices": [{"message": {"content": json.dumps({
                "action": "BUY", "confidence": 0.8,
                "reasoning": "多维度共振", "key_insights": ["insight1"],
            })}}],
            "usage": {"total_tokens": 150},
        }

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=MagicMock(),
        ))

        with patch.object(llm, '_get_client', return_value=mock_client):
            reports = {"macro": make_macro_report(), "signal": make_signal_report()}
            decision = await llm.analyze(reports)
            assert decision.action == DecisionAction.BUY
            assert decision.provider_status == ProviderStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_analyze_api_error_triggers_circuit(self, llm):
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch.object(llm, '_get_client', return_value=mock_client):
            reports = {"macro": make_macro_report()}
            with pytest.raises(Exception):
                await llm.analyze(reports)
            assert llm._cb.failure_count >= 1


# ---- LLMFallbackChain Tests ----

class TestLLMFallbackChain:
    @pytest.fixture
    def chain(self) -> LLMFallbackChain:
        primary = MagicMock(spec=OpenAICompatibleLLM)
        primary.provider_name = "deepseek"
        primary.model = "deepseek-chat"
        primary.analyze = AsyncMock(side_effect=CircuitBreakerOpenError("deepseek", 30))

        secondary = MagicMock(spec=OpenAICompatibleLLM)
        secondary.provider_name = "deepseek-reasoner"
        secondary.model = "deepseek-reasoner"
        secondary.analyze = AsyncMock(side_effect=Exception("ds-reasoner failed"))

        tertiary = MagicMock(spec=OpenAICompatibleLLM)
        tertiary.provider_name = "gemini-k1"
        tertiary.model = "gemini-2.5-pro"
        tertiary.analyze = AsyncMock(return_value=Decision(
            action=DecisionAction.BUY, confidence=0.8,
            reasoning="Gemini 分析", evidence_sources=["macro", "signal"],
            provider_label="gemini:gemini-2.5-pro", provider_status=ProviderStatus.HEALTHY,
        ))

        quaternary = MagicMock(spec=OpenAICompatibleLLM)
        quaternary.provider_name = "gemini-k2"
        quaternary.model = "gemini-2.5-pro"
        quaternary.analyze = AsyncMock(side_effect=Exception("gemini-k2 failed"))

        quinary = MagicMock(spec=OpenAICompatibleLLM)
        quinary.provider_name = "zhipu-flash"
        quinary.model = "glm-4-flash"
        quinary.analyze = AsyncMock(side_effect=Exception("zhipu-flash failed"))

        senary = MagicMock(spec=OpenAICompatibleLLM)
        senary.provider_name = "siliconflow"
        senary.model = "THUDM/GLM-Z1-9B-0414"
        senary.analyze = AsyncMock(side_effect=Exception("siliconflow failed"))

        septenary = MagicMock(spec=OpenAICompatibleLLM)
        septenary.provider_name = "qianfan"
        septenary.model = "ernie-speed-pro-128k"
        septenary.analyze = AsyncMock(side_effect=Exception("qianfan failed"))

        rule_based = MagicMock(spec=RuleBasedAnalyzer)
        rule_based.provider_name = "rule_based"
        rule_based.analyze = AsyncMock(return_value=Decision(
            action=DecisionAction.HOLD, confidence=0.3,
            reasoning="规则降级", evidence_sources=["rule"],
            provider_label="rule_based:fallback", provider_status=ProviderStatus.FALLBACK,
        ))

        return LLMFallbackChain(primary, secondary, tertiary, quaternary, quinary, senary, septenary, rule_based)

    @pytest.mark.asyncio
    async def test_falls_back_to_secondary(self, chain):
        reports = {"macro": make_macro_report(), "signal": make_signal_report()}
        decision = await chain.analyze(reports)
        assert chain.active_provider == "gemini-k1"
        assert decision.provider_label == "gemini:gemini-2.5-pro"

    @pytest.mark.asyncio
    async def test_all_fail_uses_rule_based(self, chain):
        chain.providers[0].analyze = AsyncMock(side_effect=Exception("fail1"))
        chain.providers[1].analyze = AsyncMock(side_effect=CircuitBreakerOpenError("ds-reasoner", 10))
        chain.providers[2].analyze = AsyncMock(side_effect=Exception("fail3"))
        chain.providers[3].analyze = AsyncMock(side_effect=Exception("fail4"))
        chain.providers[4].analyze = AsyncMock(side_effect=Exception("fail5"))
        chain.providers[5].analyze = AsyncMock(side_effect=Exception("fail6"))
        chain.providers[6].analyze = AsyncMock(side_effect=Exception("fail7"))

        reports = {"macro": make_macro_report()}
        decision = await chain.analyze(reports)
        assert chain.active_provider == "rule_based"
        assert decision.provider_status == ProviderStatus.FALLBACK

    @pytest.mark.asyncio
    async def test_health_check(self, chain):
        chain.providers[0].health_check = AsyncMock(return_value=True)
        chain.providers[1].health_check = AsyncMock(return_value=False)
        chain.providers[2].health_check = AsyncMock(return_value=True)
        results = await chain.health_check()
        assert results["deepseek"] is True
        assert results["deepseek-reasoner"] is False


# ---- ChiefAnalyst Tests ----

class TestChiefAnalyst:
    @pytest.fixture
    def chief(self, mock_bus) -> ChiefAnalyst:
        return ChiefAnalyst(mock_bus, CONFIG)

    @pytest.mark.asyncio
    async def test_stores_reports_triggers_decision(self, chief, mocker):
        mock_decision = Decision(
            action=DecisionAction.BUY, confidence=0.7,
            reasoning="测试决策", evidence_sources=["macro", "signal", "trace"],
            provider_label="test:model", provider_status=ProviderStatus.HEALTHY,
        )
        mocker.patch("core.chief_decision.build_chief_decision", AsyncMock(return_value=mock_decision))
        chief._publish_decision = AsyncMock()

        await chief.process_message({"event": "MACRO_REPORT", "agent": "macro",
                                      "data": {"risk_appetite_index": 0.55}, "confidence": 0.5})
        await chief.process_message({"event": "SIGNAL_REPORT", "agent": "signal",
                                      "data": {"signals": []}, "confidence": 0.4})
        await chief.process_message({"event": "TRACE_REPORT", "agent": "trace",
                                      "data": {"direction": "bullish"}, "confidence": 0.6})

        assert len(chief._reports) == 0
        assert chief._decision_count == 1
        chief._publish_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_risk_override_triggers_immediately(self, chief):
        chief._publish_decision = AsyncMock()

        await chief.process_message({
            "event": "RISK_OVERRIDE",
            "reason": "硬止损触发",
            "action": "FORCE_SELL",
            "severity": "critical",
            "agent": "risk",
        })

        assert chief._decision_count == 1
        chief._publish_decision.assert_called_once()

        call_args = chief._publish_decision.call_args[0][0]
        assert call_args.action == DecisionAction.WAIT
        assert call_args.risk_override is not None
        assert call_args.risk_override.reason == "硬止损触发"
        assert call_args.risk_override.severity == "critical"

    @pytest.mark.asyncio
    async def test_risk_safe_clears_override(self, chief):
        await chief.process_message({"event": "RISK_SAFE"})
        assert chief._risk_state == "safe"
        assert chief._risk_override is None

    @pytest.mark.asyncio
    async def test_dummy_decision_when_no_llm(self):
        from core.chief_decision import _dummy_decision
        decision = _dummy_decision("无 LLM")
        assert decision.action == DecisionAction.HOLD
        assert decision.provider_label == "chief:dummy"
        assert decision.provider_status == ProviderStatus.FALLBACK

    @pytest.mark.asyncio
    async def test_build_ai_decision_no_chain(self):
        from core.chief_decision import build_chief_decision, _dummy_decision
        decision = await build_chief_decision({}, None)
        assert decision.provider_label == "chief:dummy"
        assert decision.action == DecisionAction.HOLD

    @pytest.mark.asyncio
    async def test_status_no_llm(self, chief):
        s = chief.status
        assert s["active_llm"] == "none"
        assert s["total_decisions"] == 0

    @pytest.mark.asyncio
    async def test_emits_decision_final_event(self, chief, mock_bus):
        decision = Decision(
            action=DecisionAction.SELL, confidence=0.65,
            reasoning="测试发布", evidence_sources=["test"],
            provider_label="test:model",
        )

        await chief._publish_decision(decision)

        mock_bus.publish.assert_called()
        channel, payload = mock_bus.publish.call_args[0]
        assert channel == "decision:final"
        assert payload["event"] == "DECISION_FINAL"
        assert payload["action"] == "SELL"
        assert payload["confidence"] == 0.65

"""
Market Trace V6.0 — 共享首席决策引擎
ChiefAnalyst 和 Web API 双路径共用，确保决策逻辑一致
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from core.llm_factory import LLMFallbackChain
from core.strategies import DIVERGENCE_MIN_STRENGTH
from core.schema import (
    AgentReport,
    Decision,
    DecisionAction,
    ProviderStatus,
)


async def build_chief_decision(
    reports: dict[str, AgentReport],
    llm_chain: Optional[LLMFallbackChain],
    risk_severity: Optional[str] = None,
    risk_reason: Optional[str] = None,
) -> Decision:
    """
    共享决策引擎 - 三路分支：

    * critical  → 跳过 LLM，直接 WAIT
    * warning   → 调 LLM 但强制 HOLD，置信度 ×0.3
    * None      → 正常 LLM 决策

    双路径（Agent 事件 + Web API）均调用此函数，保障一致性。
    """
    if risk_severity == "critical":
        return Decision(
            action=DecisionAction.WAIT,
            confidence=0.0,
            reasoning=f"风控一票否决: {risk_reason or '未知原因'}",
            evidence_sources=["risk"],
            evidence_chain={"risk_override": True, "severity": "critical"},
            provider_label="risk:veto",
            provider_status=ProviderStatus.DEGRADED,
        )

    if llm_chain is None:
        return _dummy_decision("无 LLM 链路配置")

    if risk_severity:
        decision = await llm_chain.analyze(reports)
        # warning级别: 保留LLM决策, 只降置信度+标注风险, 不强制WAIT
        decision.confidence = min(decision.confidence * 0.3, 0.4)
        decision.reasoning += f" | 风控预警(置信度×0.3): {risk_reason or 'N/A'}"
        decision.provider_status = ProviderStatus.DEGRADED
        return decision

    try:
        return await llm_chain.analyze(reports)
    except Exception as e:
        logger.error("LLM 决策异常: {}", e)
        return _dummy_decision(f"LLM 调用异常: {e}")


def _dummy_decision(reason: str) -> Decision:
    return Decision(
        action=DecisionAction.HOLD,
        confidence=0.3,
        reasoning=reason,
        evidence_sources=["none"],
        evidence_chain={},
        provider_label="chief:dummy",
        provider_status=ProviderStatus.FALLBACK,
    )


def evaluate_risk_sync(
    reports: dict[str, AgentReport],
    daily_change_pct: float = 0.0,
) -> tuple[Optional[str], Optional[str]]:
    """
    同步风控检查 - 供 Web API 路径使用

    从 reports 数据中提取风险条件，确保 API 路径与 Agent 路径
    使用相同的风控标准，消除双路径不一致。

    返回: (severity, reason)  或 (None, None) 表示无风险
    """
    macro = reports.get("macro")
    trace = reports.get("trace")
    signal = reports.get("signal")

    macro_data = macro.data if macro and isinstance(macro.data, dict) else {}
    trace_data = trace.data if trace and isinstance(trace.data, dict) else {}
    signal_data = signal.data if signal and isinstance(signal.data, dict) else {}

    rai = macro_data.get("risk_appetite_index", 0.5)
    trace_direction = trace_data.get("direction", "neutral")

    signals = signal_data.get("signals", [])
    agent_signals = signal_data.get("agent_signals", [])

    indicators = signal_data.get("indicators", {})

    daily_change = indicators.get("daily_change")
    if daily_change is None:
        daily_change = daily_change_pct / 100.0 if daily_change_pct else 0

    if daily_change < 0 and abs(daily_change) >= 0.07:
        return (
            "critical",
            f"单日熔断: 日内跌幅{abs(daily_change)*100:.1f}% (阈值7%)",
        )

    all_sigs = signals + agent_signals
    for sig in all_sigs:
        if isinstance(sig, dict) and sig.get("type") == "BEARISH_DIVERGENCE":
            strength = sig.get("strength", 0)
            if strength >= DIVERGENCE_MIN_STRENGTH:
                return ("critical", "强势顶背离 → 强制平仓/减仓")

    if rai is not None and rai < 0.35 and trace_direction == "bullish":
        return (
            "warning",
            f"宏观极度悲观(RAI={rai:.2f}) vs 资金大幅流入({trace_direction})",
        )
    if rai is not None and rai > 0.65 and trace_direction == "bearish":
        return (
            "warning",
            f"宏观过度乐观(RAI={rai:.2f}) vs 资金大幅流出({trace_direction})",
        )

    return (None, None)

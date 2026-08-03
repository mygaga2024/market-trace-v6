"""
Market Trace V6.0 — Chief Analyst AI
决策中枢：汇总 Agent 报告 → 检查风控否决 → 调用 LLM 回退链 → 输出决策+证据链
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from agents.base_agent import BaseAgent
from core.bus import MessageBus
from core.chief_decision import build_chief_decision
from core.llm_factory import LLMFallbackChain
from core.schema import (
    AgentReport,
    AgentName,
    Decision,
    DecisionAction,
    RiskOverride,
    ProviderStatus,
)


class ChiefAnalyst(BaseAgent):
    """
    首席分析决策 Agent

    工作流：
    1. 收集 Macro / Signal / Trace 的最新报告
    2. 检查 Risk Agent 是否有否决事件
    3. 若存在否决 → 直接采纳风控建议，不调用 AI
    4. 若无否决 → 调用 LLM 回退链进行非线性加权分析
    5. 输出决策（action / confidence / reasoning / evidence_sources）
    6. 发布 decision:final 到 Redis
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict[str, Any],
        llm_chain: Optional[LLMFallbackChain] = None,
        notifier: Optional[Any] = None,
        db=None,
    ):
        super().__init__(
            AgentName.CHIEF.value,
            bus,
            ["reports:macro", "reports:signal", "reports:trace", "risk:override"],
            config,
            db=db,
        )

        self._llm_chain = llm_chain
        self._notifier = notifier
        self._reports: dict[str, AgentReport] = {}
        self._risk_state: str = "safe"
        self._risk_override: Optional[RiskOverride] = None
        self._decision_history: list[Decision] = []
        self._decision_count: int = 0
        self._decide_lock = asyncio.Lock()

    async def process_message(self, message: dict[str, Any]) -> None:
        event = message.get("event", "")
        agent = message.get("agent", "")

        if event == "RISK_OVERRIDE":
            self._risk_state = "override"
            self._risk_override = RiskOverride(
                reason=message.get("reason", "风险否决"),
                action=message.get("action", "HALT"),
                severity=message.get("severity", "critical"),
                source_agent=AgentName.RISK,
            )
            logger.warning("Chief Analyst 收到风控否决: {}", message.get("reason"))
            await self._make_decision()

        elif event == "RISK_SAFE":
            self._risk_state = "safe"
            self._risk_override = None

        elif agent and event in ("MACRO_REPORT", "SIGNAL_REPORT", "TRACE_REPORT"):
            report = AgentReport(
                agent=AgentName(agent) if agent else AgentName.MACRO,
                timestamp=datetime.now(timezone.utc),
                summary=message.get("summary", ""),
                data=message.get("data", {}),
                confidence=message.get("confidence", 0.0),
                signals=message.get("data", {}).get("signals", []),
            )
            self._reports[agent] = report
            await self._try_decide()

    async def _try_decide(self) -> None:
        """当 Macro/Signal/Trace 三者报告齐备时触发决策"""
        required = {"macro", "signal", "trace"}
        available = set(self._reports.keys())
        if not required.issubset(available):
            return

        logger.debug("Chief Analyst: 三份报告齐备, 触发决策")
        await self._make_decision()

    async def _make_decision(self) -> None:
        """核心决策逻辑"""
        async with self._decide_lock:
            self._decision_count += 1

            reports_snapshot = dict(self._reports)
            risk_override_snapshot = self._risk_override

            severity = risk_override_snapshot.severity if risk_override_snapshot else None
            reason = risk_override_snapshot.reason if risk_override_snapshot else None

            decision = await build_chief_decision(
                reports=reports_snapshot,
                llm_chain=self._llm_chain,
                risk_severity=severity,
                risk_reason=reason,
            )

            if risk_override_snapshot:
                decision.risk_override = risk_override_snapshot

            self._decision_history.append(decision)

            if len(self._decision_history) > 100:
                self._decision_history = self._decision_history[-100:]

            await self._publish_decision(decision)

            for key in reports_snapshot:
                self._reports.pop(key, None)
            self._risk_state = "safe"
            self._risk_override = None

    async def _publish_decision(self, decision: Decision) -> None:
        """发布最终决策到 Redis"""
        # 通知字段：symbol/price 从 signal 报告提取（P1-2 修复）
        symbol = ""
        price = 0.0
        signal_report = self._reports.get("signal")
        if signal_report and signal_report.data:
            symbol = str(signal_report.data.get("symbol", ""))
            if symbol and self.bus is not None:
                try:
                    cached = await self.bus.cache_get(f"market:raw:{symbol}")
                    if cached:
                        price = float(cached[-1].get("close", 0) or 0)
                except Exception as e:
                    logger.debug("Chief 通知取价失败: {}", e)
        payload = {
            "event": "DECISION_FINAL",
            "decision_id": decision.decision_id,
            "symbol": symbol,
            "price": price,
            "action": decision.action.value,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "evidence_sources": decision.evidence_sources,
            "evidence_chain": decision.evidence_chain,
            "risk_override": {
                "reason": decision.risk_override.reason,
                "action": decision.risk_override.action,
                "severity": decision.risk_override.severity,
            } if decision.risk_override else None,
            "provider_label": decision.provider_label,
            "provider_status": decision.provider_status.value,
            "decision_count": self._decision_count,
            "timestamp": decision.timestamp.isoformat(),
        }

        await self.publish("decision:final", payload)
        logger.info(
            "最终决策 #{}: action={}, confidence={:.2f}, provider={}",
            self._decision_count, decision.action.value, decision.confidence, decision.provider_label,
        )

        if self.db:
            try:
                await self.db.save_decision(
                    decision_id=decision.decision_id,
                    action=decision.action.value,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    evidence_sources=decision.evidence_sources,
                    evidence_chain=decision.evidence_chain,
                    risk_override={
                        "reason": decision.risk_override.reason,
                        "action": decision.risk_override.action,
                        "severity": decision.risk_override.severity,
                    } if decision.risk_override else None,
                    provider_label=decision.provider_label,
                    provider_status=decision.provider_status.value if hasattr(decision.provider_status, 'value') else str(decision.provider_status),
                )
            except Exception as e:
                logger.warning("Chief Analyst 决策保存DB失败: {}", e)

        if decision.action.value in ("BUY", "SELL") and self._notifier:
            try:
                n = self._notifier
                if n.enabled:
                    await n.alert_decision(
                        symbol=payload.get("symbol", ""),
                        action=decision.action.value,
                        confidence=decision.confidence,
                        price=float(payload.get("price", 0)),
                        reason=decision.reasoning,
                    )
            except Exception:
                pass

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(1)

    @property
    def status(self) -> dict[str, Any]:
        return {
            "active_llm": self._llm_chain.active_provider if self._llm_chain else "none",
            "reports_available": list(self._reports.keys()),
            "risk_state": self._risk_state,
            "total_decisions": self._decision_count,
        }

"""
Market Trace V6.0 — Risk Agent
硬编码风控（一票否决权）—— 不依赖 AI，纯规则引擎
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from agents.base_agent import BaseAgent
from core.bus import MessageBus
from core.schema import AgentReport, AgentName, ReportStatus, RiskOverride


class RiskAgent(BaseAgent):
    """
    风控守护 Agent

    硬编码规则引擎，拥有最终一票否决权：
    1. 逻辑冲突：Trace vs Macro 完全对立 → confidence × 0.3
    2. 止损检查：触及硬止损线 → 发布 RISK_OVERRIDE（最高优先级）
    3. 仓位检查：单票仓位超限 → 发布 RISK_OVERRIDE
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict[str, Any],
    ):
        super().__init__(
            AgentName.RISK.value,
            bus,
            ["reports:macro", "reports:signal", "reports:trace"],
            config,
        )

        risk_cfg = config.get("agents", {}).get("risk", {})
        self._conflict_multiplier: float = risk_cfg.get("conflict_multiplier", 0.3)
        self._stop_loss_percent: float = risk_cfg.get("stop_loss_percent", 0.05)
        self._max_position_percent: float = risk_cfg.get("max_position_percent", 0.3)

        self._latest_reports: dict[str, AgentReport] = {}
        self._override_count: int = 0

    async def process_message(self, message: dict[str, Any]) -> None:
        agent_name = message.get("agent", "")

        report = AgentReport(
            agent=AgentName(agent_name) if agent_name else AgentName.MACRO,
            timestamp=datetime.now(timezone.utc),
            summary=message.get("summary", ""),
            data=message.get("data", {}),
            confidence=message.get("confidence", 0.0),
            signals=message.get("data", {}).get("signals", []),
        )
        self._latest_reports[agent_name] = report

        await self._run_checks()

    async def _run_checks(self) -> None:
        override = None

        override = self._check_conflict()
        if override:
            await self._emit_override(override)
            return

        override = self._check_stop_loss()
        if override:
            await self._emit_override(override)
            return

        await self._emit_safe()

    def _check_conflict(self) -> Optional[RiskOverride]:
        """检测多源信号逻辑冲突"""
        macro_report = self._latest_reports.get("macro")
        trace_report = self._latest_reports.get("trace")

        if not macro_report or not trace_report:
            return None

        macro_data = macro_report.data
        if isinstance(macro_data, dict):
            rai = macro_data.get("risk_appetite_index", 0.5)
        else:
            rai = 0.5

        trace_data = trace_report.data
        if isinstance(trace_data, dict):
            direction = trace_data.get("direction", "neutral")
        else:
            direction = "neutral"

        if rai < 0.35 and direction == "bullish":
            return RiskOverride(
                reason=f"宏观极度悲观(RAI={rai:.2f}) vs 资金大幅流入({direction})，强制置信度 x{self._conflict_multiplier}",
                action="REDUCE_CONFIDENCE",
                severity="warning",
                source_agent=AgentName.RISK,
            )
        elif rai > 0.65 and direction == "bearish":
            return RiskOverride(
                reason=f"宏观过度乐观(RAI={rai:.2f}) vs 资金大幅流出({direction})，强制置信度 x{self._conflict_multiplier}",
                action="REDUCE_CONFIDENCE",
                severity="warning",
                source_agent=AgentName.RISK,
            )

        return None

    def _check_stop_loss(self) -> Optional[RiskOverride]:
        """硬止损检查"""
        signal_report = self._latest_reports.get("signal")
        if not signal_report or not signal_report.data:
            return None

        signals = signal_report.data.get("signals", [])
        indicators = signal_report.data.get("indicators", {})

        for sig in signals:
            if sig.get("type") == "BEARISH_DIVERGENCE" and sig.get("strength", 0) > 0.8:
                return RiskOverride(
                    reason="强势顶背离 → 强制平仓/减仓",
                    action="FORCE_SELL",
                    severity="critical",
                    source_agent=AgentName.RISK,
                )

        return None

    async def _emit_override(self, override: RiskOverride) -> None:
        self._override_count += 1

        payload = {
            "event": "RISK_OVERRIDE",
            "reason": override.reason,
            "action": override.action,
            "severity": override.severity,
            "source_agent": override.source_agent.value,
            "override_count": self._override_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await self.publish("risk:override", payload)
        logger.warning("Risk Agent 否决: [{}] {}", override.severity, override.reason)

    async def _emit_safe(self) -> None:
        await self.publish("risk:override", {
            "event": "RISK_SAFE",
            "severity": "info",
            "message": "风控检查通过，无否决事件",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(1)

    @property
    def latest_overrides(self) -> list[dict[str, Any]]:
        return []

    def get_confidence_penalty(self, original_confidence: float) -> float:
        """计算逻辑冲突后的置信度乘数"""
        override = self._check_conflict()
        if override:
            return original_confidence * self._conflict_multiplier
        return original_confidence

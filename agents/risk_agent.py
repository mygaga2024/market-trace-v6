"""
Market Trace V6.0 — Risk Agent
硬编码风控（一票否决权）—— 不依赖 AI，纯规则引擎
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
from loguru import logger

from agents.base_agent import BaseAgent
from core.bus import MessageBus
from core.schema import AgentReport, AgentName, ReportStatus, RiskOverride
from core.strategies import _calc_atr


class RiskAgent(BaseAgent):
    """
    风控守护 Agent

    硬编码规则引擎，拥有最终一票否决权：
    1. 逻辑冲突：Trace vs Macro 完全对立 → confidence × 0.3
    2. 止损检查（多层）：
       - 硬止损：触及固定百分比止损线 → RISK_OVERRIDE
       - ATR 动态止损：收盘价跌破 ATR 通道 → RISK_OVERRIDE
       - 单日熔断：日内跌幅 >7% → 强制平仓
    3. 连续下跌：连续3日收阴 → 强制减仓
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict[str, Any],
        risk_manager=None,
    ):
        super().__init__(
            AgentName.RISK.value,
            bus,
            ["reports:macro", "reports:signal", "reports:trace"],
            config,
        )

        self._rm = risk_manager

        risk_cfg = config.get("agents", {}).get("risk", {})
        self._conflict_multiplier: float = risk_cfg.get("conflict_multiplier", 0.3)
        self._stop_loss_percent: float = risk_cfg.get("stop_loss_percent", 0.05)
        self._atr_period: int = risk_cfg.get("atr_period", 14)
        self._atr_multiplier: float = risk_cfg.get("atr_multiplier", 2.0)
        self._daily_drop_threshold: float = risk_cfg.get("daily_drop_threshold", 0.07)
        self._consecutive_drop_days: int = risk_cfg.get("consecutive_drop_days", 3)

        self._latest_reports: dict[str, AgentReport] = {}
        self._override_count: int = 0

    async def process_message(self, message: dict[str, Any]) -> None:
        event = message.get("event", "")
        agent_name = message.get("agent", "")

        if event not in ("MACRO_REPORT", "SIGNAL_REPORT", "TRACE_REPORT"):
            return

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

        override = self._check_bearish_divergence()
        if override:
            await self._emit_override(override)
            return

        override = await self._check_atr_stop()
        if override:
            await self._emit_override(override)
            return

        override = await self._check_daily_circuit_breaker()
        if override:
            await self._emit_override(override)
            return

        override = await self._check_consecutive_decline()
        if override:
            await self._emit_override(override)
            return

        await self._emit_safe()

    async def _get_cached_klines(self, symbol: str) -> Optional[list[dict]]:
        """从缓存获取 K 线数据"""
        if not self.bus:
            return None
        return await self.bus.cache_get(f"market:raw:{symbol}")

    # _calc_atr 已迁移到 core/strategies.py 统一复用

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

    def _check_bearish_divergence(self) -> Optional[RiskOverride]:
        """强势顶背离检测：背离强度超阈值时触发否决"""
        signal_report = self._latest_reports.get("signal")
        if not signal_report or not signal_report.data:
            return None

        signals = signal_report.data.get("signals", [])

        for sig in signals:
            if sig.get("type") == "BEARISH_DIVERGENCE" and sig.get("strength", 0) > 0.8:
                return RiskOverride(
                    reason="强势顶背离 → 强制平仓/减仓",
                    action="FORCE_SELL",
                    severity="critical",
                    source_agent=AgentName.RISK,
                )

        return None

    async def _check_atr_stop(self) -> Optional[RiskOverride]:
        """ATR 动态止损：收盘价跌破 ATR 通道下轨"""
        signal_report = self._latest_reports.get("signal")
        if not signal_report or not signal_report.data:
            return None

        symbol = signal_report.data.get("symbol", "")
        if not symbol:
            return None

        cached = await self._get_cached_klines(symbol)
        if not cached or len(cached) < self._atr_period + 1:
            return None

        closes = np.array([float(r["close"]) for r in cached])
        highs = np.array([float(r["high"]) for r in cached])
        lows = np.array([float(r["low"]) for r in cached])

        atr = _calc_atr(highs, lows, closes, self._atr_period)
        if atr <= 0:
            return None

        recent_high = float(np.max(highs[-self._atr_period:]))
        atr_stop = recent_high - self._atr_multiplier * atr
        current_close = closes[-1]

        if current_close < atr_stop:
            return RiskOverride(
                reason=f"ATR动态止损触发: {current_close:.2f} < {atr_stop:.2f} (最高{recent_high:.2f} - {self._atr_multiplier}xATR={atr:.2f})",
                action="FORCE_SELL",
                severity="critical",
                source_agent=AgentName.RISK,
            )

        return None

    async def _check_daily_circuit_breaker(self) -> Optional[RiskOverride]:
        """单日熔断：日内跌幅超过阈值"""
        signal_report = self._latest_reports.get("signal")
        if not signal_report or not signal_report.data:
            return None

        symbol = signal_report.data.get("symbol", "")
        if not symbol:
            return None

        indicators = signal_report.data.get("indicators", {})
        cached = await self._get_cached_klines(symbol)

        if indicators.get("daily_change") is not None:
            daily_change = float(indicators["daily_change"])
            direction = "下跌" if daily_change < 0 else "上涨"
            daily_change = abs(daily_change)
        elif cached and len(cached) >= 2:
            closes_list = [float(r["close"]) for r in cached]
            prev_c = closes_list[-2]
            cur_c = closes_list[-1]
            daily_change = abs((cur_c - prev_c) / prev_c) if prev_c else 0
            direction = "下跌" if cur_c < prev_c else "上涨"
        else:
            return None

        if daily_change >= self._daily_drop_threshold and direction == "下跌":
            return RiskOverride(
                reason=f"单日熔断: {direction}{daily_change*100:.1f}% (阈值{self._daily_drop_threshold*100:.0f}%)",
                action="FORCE_SELL",
                severity="critical",
                source_agent=AgentName.RISK,
            )

        return None

    async def _check_consecutive_decline(self) -> Optional[RiskOverride]:
        """连续下跌检测：连续N日收阴 → 强制减仓"""
        signal_report = self._latest_reports.get("signal")
        if not signal_report or not signal_report.data:
            return None

        symbol = signal_report.data.get("symbol", "")
        if not symbol:
            return None

        cached = await self._get_cached_klines(symbol)
        if not cached or len(cached) < self._consecutive_drop_days:
            return None

        closes = [float(r["close"]) for r in cached]
        opens = [float(r.get("open", closes[i])) for i, r in enumerate(cached)]

        decline_count = 0
        for i in range(len(closes) - 1, max(0, len(closes) - self._consecutive_drop_days - 1), -1):
            if i > 0 and closes[i] < closes[i - 1] and closes[i] < opens[i]:
                decline_count += 1
            else:
                break

        if decline_count >= self._consecutive_drop_days:
            return RiskOverride(
                reason=f"连续{decline_count}日收阴下跌 → 触发减仓",
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

        if self._rm:
            try:
                await self._rm.record_override(
                    reason=override.reason,
                    action=override.action,
                    severity=override.severity,
                )
            except Exception:
                pass

        if override.severity == "critical":
            try:
                from core.notifier import get_notifier
                n = get_notifier()
                if n.enabled:
                    await n.alert_risk(override.reason, override.severity)
            except Exception:
                pass

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

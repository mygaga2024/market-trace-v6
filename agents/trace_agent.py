"""
Market Trace V6.0 — Trace Agent
Level-2 异动扫描、大单流向、资金切入痕迹检测
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
from loguru import logger

from agents.base_agent import BaseAgent
from core.bus import MessageBus
from core.schema import AgentReport, AgentName, ReportStatus
from data_provider.akshare_impl import AkShareProvider


class TraceAgent(BaseAgent):
    """
    资金痕迹追踪 Agent

    监听 DATA_UPDATED 和 FUND_FLOW_UPDATED，
    检测大单异动、资金流速突变、筹码集中度变化。
    此为核心捕猎 Agent——捕捉主力资金介入痕迹。
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict[str, Any],
        data_provider: Optional[AkShareProvider] = None,
    ):
        super().__init__(AgentName.TRACE.value, bus, ["events:data"], config)

        trace_cfg = config.get("agents", {}).get("trace", {})
        self._big_order_threshold: float = trace_cfg.get("big_order_threshold", 1_000_000)
        self._anomaly_zscore: float = trace_cfg.get("anomaly_zscore", 2.5)
        self._fund_flow_window: int = trace_cfg.get("fund_flow_window", 5)
        self._concentration_threshold: float = trace_cfg.get("concentration_threshold", 0.7)

        self._provider = data_provider
        self._flow_history: dict[str, list[float]] = {}

    async def process_message(self, message: dict[str, Any]) -> None:
        event = message.get("event", "")
        symbol = message.get("symbol", "")
        if not symbol:
            return

        if event in ("DATA_UPDATED", "FUND_FLOW_UPDATED"):
            await self._trace_symbol(symbol)

    async def _trace_symbol(self, symbol: str) -> None:
        """对单个标的执行资金痕迹扫描"""
        fund_flow = None
        if self._provider:
            fund_flow = await self._provider.fetch_fund_flow(symbol)

        cached = await self.bus.cache_get(f"market:fundflow:{symbol}")
        if not fund_flow and cached:
            fund_flow = cached

        if not fund_flow:
            logger.debug("Trace Agent: {} 无资金流向数据", symbol)
            return

        signals: list[dict[str, Any]] = []

        main_net = fund_flow.get("main_net_inflow", 0)
        main_pct = fund_flow.get("main_net_inflow_pct", 0)
        super_large = fund_flow.get("super_large_net", 0)
        large_net = fund_flow.get("large_net", 0)

        self._detect_big_order(symbol, main_net, super_large, signals)
        self._detect_flow_anomaly(symbol, main_net, signals)
        self._detect_concentration_shift(super_large, large_net, signals)

        signal_count = len(signals)
        confidence = min(1.0, signal_count * 0.3) if signal_count > 0 else 0.0

        direction = self._determine_direction(signals)

        report = AgentReport(
            agent=AgentName.TRACE,
            timestamp=datetime.now(timezone.utc),
            summary=self._make_summary(signals, direction),
            status=ReportStatus.OK,
            data={
                "symbol": symbol,
                "fund_flow": fund_flow,
                "signals": signals,
                "direction": direction,
                "signal_count": signal_count,
            },
            confidence=confidence,
            signals=signals,
        )

        await self.publish("reports:trace", {
            "event": "TRACE_REPORT",
            "report_id": report.report_id,
            "agent": report.agent.value,
            "symbol": symbol,
            "summary": report.summary,
            "data": report.data,
            "confidence": report.confidence,
            "timestamp": report.timestamp.isoformat(),
        })

        logger.info("Trace Agent {} 报告: {} 信号, 方向={}", symbol, signal_count, direction)

    def _detect_big_order(
        self, symbol: str, main_net: float, super_large: float, signals: list
    ) -> None:
        """大单检测"""
        if main_net > self._big_order_threshold:
            signals.append({
                "type": "BIG_ORDER_INFLOW",
                "direction": "bullish",
                "value": main_net,
                "threshold": self._big_order_threshold,
                "strength": 0.5,
            })
        elif main_net < -self._big_order_threshold:
            signals.append({
                "type": "BIG_ORDER_OUTFLOW",
                "direction": "bearish",
                "value": main_net,
                "strength": 0.5,
            })

        if super_large > self._big_order_threshold * 0.5:
            signals.append({
                "type": "SUPER_LARGE_INFLOW",
                "direction": "bullish",
                "value": super_large,
                "strength": 0.7,
            })

    def _detect_flow_anomaly(self, symbol: str, main_net: float, signals: list) -> None:
        """资金流速异常检测（Z-score）"""
        history = self._flow_history.setdefault(symbol, [])
        history.append(main_net)

        window = self._fund_flow_window
        if len(history) > window * 2:
            history[:] = history[-window * 2:]

        if len(history) < window:
            return

        recent = np.array(history[-window:])
        mean_val = np.mean(recent)
        std_val = np.std(recent)

        if std_val < 1e-9:
            return

        z = (main_net - mean_val) / std_val

        if abs(z) > self._anomaly_zscore:
            direction = "bullish" if z > 0 else "bearish"
            signals.append({
                "type": "FLOW_ZSCORE_ANOMALY",
                "direction": direction,
                "z_score": round(z, 2),
                "threshold": self._anomaly_zscore,
                "strength": min(0.9, abs(z) / (self._anomaly_zscore * 2)),
            })

    def _detect_concentration_shift(self, super_large: float, large_net: float, signals: list) -> None:
        """筹码集中度变化检测"""
        total_large = abs(super_large) + abs(large_net)
        if total_large < 1e-9:
            return

        super_ratio = abs(super_large) / total_large

        if super_ratio > self._concentration_threshold and super_large > 0:
            signals.append({
                "type": "CONCENTRATION_ACCUMULATION",
                "direction": "bullish",
                "ratio": round(super_ratio, 3),
                "strength": 0.6,
            })
        elif super_ratio > self._concentration_threshold and super_large < 0:
            signals.append({
                "type": "CONCENTRATION_DISTRIBUTION",
                "direction": "bearish",
                "ratio": round(super_ratio, 3),
                "strength": 0.6,
            })

    @staticmethod
    def _determine_direction(signals: list) -> str:
        bullish = sum(1 for s in signals if s["direction"] == "bullish")
        bearish = sum(1 for s in signals if s["direction"] == "bearish")
        if bullish > bearish:
            return "bullish"
        elif bearish > bullish:
            return "bearish"
        return "neutral"

    @staticmethod
    def _make_summary(signals: list, direction: str) -> str:
        if not signals:
            return "资金流正常，无异动"
        types = [s["type"] for s in signals]
        return f"资金异动: {', '.join(types)}"

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(1)

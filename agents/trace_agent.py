"""
Market Trace V6.0 — Trace Agent
资金痕迹追踪：成交量异动、价量关系、主力行为检测（适配东财WAF后的降级方案）
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


class TraceAgent(BaseAgent):
    """
    资金痕迹追踪 Agent (适配版)

    因东财 WAF 拦截实时资金流向接口，改用成交量异动 + 价量关系分析：
    - 成交量突增：当前量 > N 倍均量 → 主力介入信号
    - 价量背离：价涨量缩 OR 价跌量增 → 预警信号
    - 量价同步：价涨量增 → 多头确认
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any], data_provider=None, db=None):
        super().__init__(AgentName.TRACE.value, bus, ["events:data"], config, db=db)

        trace_cfg = config.get("agents", {}).get("trace", {})
        self._big_order_threshold: float = trace_cfg.get("big_order_threshold", 1_000_000)
        self._anomaly_zscore: float = trace_cfg.get("anomaly_zscore", 2.5)
        self._fund_flow_window: int = trace_cfg.get("fund_flow_window", 5)
        self._concentration_threshold: float = trace_cfg.get("concentration_threshold", 0.7)
        self._volume_multiplier: float = 2.0
        self._volume_history: dict[str, list[float]] = {}
        self._price_history: dict[str, list[float]] = {}

    async def process_message(self, message: dict[str, Any]) -> None:
        event = message.get("event", "")
        symbol = message.get("symbol", "")
        if not symbol:
            return

        if event in ("DATA_UPDATED", "FUND_FLOW_UPDATED"):
            await self._trace_symbol(symbol)

    async def _trace_symbol(self, symbol: str) -> None:
        """基于 K 线缓存的成交量异动检测"""
        cached = await self.bus.cache_get(f"market:raw:{symbol}")
        if not cached:
            logger.debug("Trace Agent: {} 无缓存数据", symbol)
            return

        closes = np.array([float(r.get("close", 0)) for r in cached])
        volumes = np.array([float(r.get("volume", 0)) for r in cached])
        amounts = np.array([float(r.get("amount", 0) or 0) for r in cached])
        highs = np.array([float(r.get("high", 0)) for r in cached])
        lows = np.array([float(r.get("low", 0)) for r in cached])

        if len(closes) < 10:
            logger.debug("Trace Agent: {} 数据不足", symbol)
            return

        signals: list[dict[str, Any]] = []

        self._detect_volume_spike(volumes, closes, signals)
        self._detect_price_volume_divergence(closes, volumes, signals)
        self._detect_volume_price_trend(closes, volumes, signals)
        self._detect_range_breakout(highs, lows, closes, volumes, signals)

        signal_count = len(signals)
        strength_sum = sum(s.get("strength", 0.3) for s in signals)
        confidence = min(1.0, strength_sum * 0.5) if signal_count > 0 else 0.0
        direction = self._determine_direction(signals)

        report = AgentReport(
            agent=AgentName.TRACE,
            timestamp=datetime.now(timezone.utc),
            summary=self._make_summary(signals, direction),
            status=ReportStatus.OK,
            data={
                "symbol": symbol,
                "fund_flow": {"source": "volume_based", "note": "东财WAF适配: 成交量替代资金流向"},
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

        if self.db:
            try:
                await self.db.save_report(
                    report_id=report.report_id, agent=report.agent.value,
                    symbol=symbol, summary=report.summary, data=report.data,
                    confidence=report.confidence, status=report.status.value,
                )
            except Exception as e:
                logger.warning("Trace Agent 报告保存DB失败: {}", e)

    def _detect_volume_spike(self, volumes: np.ndarray, closes: np.ndarray, signals: list) -> None:
        """成交量突增检测"""
        if len(volumes) < 3:
            return
        avg_vol = np.mean(volumes[:-1])
        last_vol = volumes[-1]

        if avg_vol > 0 and last_vol > avg_vol * self._volume_multiplier:
            direction = "bullish" if closes[-1] > closes[-2] else "bearish"
            signals.append({
                "type": "VOLUME_SPIKE",
                "direction": direction,
                "ratio": round(last_vol / avg_vol, 2),
                "strength": min(0.8, (last_vol / avg_vol - 1) * 0.3),
            })

    def _detect_price_volume_divergence(
        self, closes: np.ndarray, volumes: np.ndarray, signals: list
    ) -> None:
        """价量背离检测"""
        if len(closes) < 5 or len(volumes) < 5:
            return
        price_change = (closes[-1] - closes[-5]) / closes[-5]
        vol_change = (volumes[-1] - np.mean(volumes[-5:-1])) / np.mean(volumes[-5:-1]) if np.mean(volumes[-5:-1]) > 0 else 0

        if price_change > 0.03 and vol_change < -0.2:
            signals.append({
                "type": "BULLISH_DIVERGENCE_WEAK_VOLUME",
                "direction": "bearish",
                "note": "价涨量缩，上涨乏力",
                "strength": 0.5,
            })
        elif price_change < -0.03 and vol_change > 0.5:
            signals.append({
                "type": "BEARISH_DIVERGENCE_HIGH_VOLUME",
                "direction": "bearish",
                "note": "价跌量增，恐慌抛售",
                "strength": 0.6,
            })

    def _detect_volume_price_trend(
        self, closes: np.ndarray, volumes: np.ndarray, signals: list
    ) -> None:
        """量价同步确认"""
        if len(closes) < 5:
            return
        price_up = closes[-1] > closes[-5]
        vol_avg_5 = np.mean(volumes[-5:])
        vol_avg_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol_avg_5

        if price_up and vol_avg_5 > vol_avg_20 * 1.2:
            signals.append({
                "type": "VOLUME_CONFIRMS_UPTREND",
                "direction": "bullish",
                "note": "价涨量增，多头确认",
                "strength": 0.6,
            })
        elif not price_up and vol_avg_5 > vol_avg_20 * 1.2:
            signals.append({
                "type": "VOLUME_CONFIRMS_DOWNTREND",
                "direction": "bearish",
                "note": "价跌量增，空头确认",
                "strength": 0.5,
            })

    def _detect_range_breakout(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        volumes: np.ndarray, signals: list
    ) -> None:
        """突破检测"""
        if len(highs) < 20:
            return
        high_20 = np.max(highs[-20:-1])
        low_20 = np.min(lows[-20:-1])
        avg_vol_20 = np.mean(volumes[-20:-1])
        last_vol = volumes[-1]

        if closes[-1] > high_20 and last_vol > avg_vol_20 * 1.3:
            signals.append({
                "type": "BREAKOUT_HIGH_VOLUME",
                "direction": "bullish",
                "strength": 0.7,
            })
        elif closes[-1] < low_20 and last_vol > avg_vol_20 * 1.3:
            signals.append({
                "type": "BREAKDOWN_HIGH_VOLUME",
                "direction": "bearish",
                "strength": 0.7,
            })

    @staticmethod
    def _determine_direction(signals: list) -> str:
        """按信号强度加权投票决定方向（避免 1 条弱信号与 1 条强信号等权）"""
        bull = sum(s.get("strength", 0.3) for s in signals if s.get("direction") == "bullish")
        bear = sum(s.get("strength", 0.3) for s in signals if s.get("direction") == "bearish")
        if bull > bear:
            return "bullish"
        elif bear > bull:
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

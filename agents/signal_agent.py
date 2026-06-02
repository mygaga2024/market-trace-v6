"""
Market Trace V6.0 — Signal Agent
K 线、均线、MACD、RSI 等传统技术指标背离与共振检测
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
from core.memory import CaseMemory


class SignalAgent(BaseAgent):
    """
    技术指标分析 Agent

    监听 DATA_UPDATED，实时计算 MA/MACD/RSI，
    识别金叉/死叉、顶背离/底背离，输出信号强度与可靠性评分。
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict[str, Any],
        memory: Optional[CaseMemory] = None,
    ):
        super().__init__(AgentName.SIGNAL.value, bus, ["events:data"], config)

        sig_cfg = config.get("agents", {}).get("signal", {})
        self._ma_periods: list[int] = sig_cfg.get("ma_periods", [5, 10, 20, 60])
        self._macd_fast: int = sig_cfg.get("macd_fast", 12)
        self._macd_slow: int = sig_cfg.get("macd_slow", 26)
        self._macd_signal: int = sig_cfg.get("macd_signal", 9)
        self._rsi_period: int = sig_cfg.get("rsi_period", 14)
        self._divergence_lookback: int = sig_cfg.get("divergence_lookback", 20)

        self._memory = memory

    async def process_message(self, message: dict[str, Any]) -> None:
        event = message.get("event", "")
        symbol = message.get("symbol", "")

        if event != "DATA_UPDATED" or not symbol:
            return

        logger.debug("Signal Agent 接收到 {} 的 DATA_UPDATED", symbol)
        await self._analyze_symbol(symbol)

    async def _analyze_symbol(self, symbol: str) -> None:
        """对单个标的执行完整技术分析"""
        cached = await self.bus.cache_get(f"market:raw:{symbol}")
        if not cached:
            logger.warning("Signal Agent: {} 无缓存 K 线数据", symbol)
            return

        closep = self._extract_close(cached)
        highp = self._extract_high(cached)
        lowp = self._extract_low(cached)
        volumes = self._extract_volume(cached)

        if len(closep) < max(self._ma_periods):
            logger.warning("Signal Agent: {} K 线不足", symbol)
            return

        signals: list[dict[str, Any]] = []
        indicators: dict[str, Any] = {}

        ma_values = {p: self._calc_ma(closep, p) for p in self._ma_periods}
        indicators["ma"] = {str(k): round(float(v[-1]), 4) for k, v in ma_values.items()} if ma_values else {}

        macd = self._calc_macd(closep)
        if macd:
            indicators["macd"] = {
                "dif": round(float(macd["dif"][-1]), 4),
                "dea": round(float(macd["dea"][-1]), 4),
                "histogram": round(float(macd["hist"][-1]), 4),
            }
            self._detect_cross(macd, signals)

        rsi = self._calc_rsi(closep, self._rsi_period)
        if rsi is not None and len(rsi) > 0:
            rsi_val = round(float(rsi[-1]), 4)
            indicators["rsi"] = rsi_val
            self._detect_rsi_signal(rsi_val, signals)
            self._detect_divergence(closep, highp, lowp, rsi, signals)

        signal_count = len(signals)
        signal_strength = min(1.0, signal_count * 0.25) if signal_count > 0 else 0.0

        reliability = self._estimate_reliability(symbol, closep, signal_count, np.array(volumes))

        report = AgentReport(
            agent=AgentName.SIGNAL,
            timestamp=datetime.now(timezone.utc),
            summary=self._make_summary(signals),
            status=ReportStatus.OK,
            data={
                "symbol": symbol,
                "indicators": indicators,
                "signals": signals,
                "signal_count": signal_count,
            },
            confidence=signal_strength,
            signals=signals,
        )
        report.data["reliability"] = reliability

        await self.publish("reports:signal", {
            "event": "SIGNAL_REPORT",
            "report_id": report.report_id,
            "agent": report.agent.value,
            "symbol": symbol,
            "summary": report.summary,
            "data": report.data,
            "confidence": report.confidence,
            "timestamp": report.timestamp.isoformat(),
        })

        logger.info("Signal Agent {} 报告: {} 信号, 强度={:.2f}", symbol, signal_count, signal_strength)

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(1)

    # ---- 指标计算 ----

    @staticmethod
    def _extract_close(cached: list) -> np.ndarray:
        return np.array([float(r.get("close", 0)) for r in cached])

    @staticmethod
    def _extract_high(cached: list) -> np.ndarray:
        return np.array([float(r.get("high", 0)) for r in cached])

    @staticmethod
    def _extract_low(cached: list) -> np.ndarray:
        return np.array([float(r.get("low", 0)) for r in cached])

    @staticmethod
    def _extract_volume(cached: list) -> np.ndarray:
        return np.array([float(r.get("volume", 0)) for r in cached])

    @staticmethod
    def _calc_ma(data: np.ndarray, period: int) -> np.ndarray:
        if len(data) < period:
            return np.array([])
        kernel = np.ones(period) / period
        conv = np.convolve(data, kernel, mode="valid")  # length = len(data) - period + 1
        ma = np.full(len(data), np.nan)
        ma[period - 1 :] = conv
        return ma

    @staticmethod
    def _calc_ema(data: np.ndarray, period: int) -> np.ndarray:
        if len(data) < period:
            return np.array([])
        alpha = 2.0 / (period + 1)
        ema = np.zeros(len(data))
        ema[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        ema[: period - 1] = np.nan
        return ema

    def _calc_macd(self, closep: np.ndarray) -> Optional[dict[str, np.ndarray]]:
        if len(closep) < self._macd_slow + self._macd_signal:
            return None
        ema_fast = self._calc_ema(closep, self._macd_fast)
        ema_slow = self._calc_ema(closep, self._macd_slow)
        dif = ema_fast - ema_slow
        dea = self._calc_ema(dif[~np.isnan(dif)], self._macd_signal) if len(dif[~np.isnan(dif)]) > 0 else np.array([])
        if len(dea) == 0:
            return None
        dea_full = np.full(len(dif), np.nan)
        dea_start = len(dif) - len(dea)
        dea_full[dea_start:] = dea
        hist = 2 * (dif - dea_full)
        return {"dif": dif, "dea": dea_full, "hist": hist}

    @staticmethod
    def _calc_rsi(closep: np.ndarray, period: int = 14) -> Optional[np.ndarray]:
        if len(closep) < period + 1:
            return None
        delta = np.diff(closep)
        rsi = np.full(len(closep), np.nan)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])
        for i in range(period, len(delta)):
            avg_gain = (avg_gain * (period - 1) + gain[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i]) / period
            if avg_loss == 0:
                rsi[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)
        return rsi

    # ---- 信号检测 ----

    def _detect_cross(self, macd: dict, signals: list) -> None:
        dif, dea, hist = macd["dif"], macd["dea"], macd["hist"]
        n = len(dif)
        if n < 2:
            return
        last = hist[-1]
        prev = hist[-2]

        if prev <= 0 and last > 0:
            signals.append({"type": "MACD_GOLDEN_CROSS", "direction": "bullish", "strength": 0.5})
        elif prev >= 0 and last < 0:
            signals.append({"type": "MACD_DEATH_CROSS", "direction": "bearish", "strength": 0.5})

        if n >= 3:
            valid_dif = dif[~np.isnan(dif)]
            valid_dea = dea[~np.isnan(dea)]
            if len(valid_dif) >= 2 and len(valid_dea) >= 2:
                if valid_dif[-2] <= valid_dea[-2] and valid_dif[-1] > valid_dea[-1]:
                    signals.append({"type": "MACD_BULLISH", "direction": "bullish", "strength": 0.6})
                elif valid_dif[-2] >= valid_dea[-2] and valid_dif[-1] < valid_dea[-1]:
                    signals.append({"type": "MACD_BEARISH", "direction": "bearish", "strength": 0.6})

    @staticmethod
    def _detect_rsi_signal(rsi_val: float, signals: list) -> None:
        if rsi_val >= 70:
            signals.append({"type": "RSI_OVERBOUGHT", "direction": "bearish", "value": rsi_val, "strength": 0.3})
        elif rsi_val <= 30:
            signals.append({"type": "RSI_OVERSOLD", "direction": "bullish", "value": rsi_val, "strength": 0.3})

    def _detect_divergence(
        self, closep: np.ndarray, highp: np.ndarray, lowp: np.ndarray, rsi: np.ndarray, signals: list
    ) -> None:
        """检测顶背离/底背离"""
        lookback = min(self._divergence_lookback, len(closep), len(rsi))
        if lookback < 5:
            return

        window = closep[-lookback:]
        rsi_window = rsi[-lookback:]

        valid = ~np.isnan(rsi_window)
        if np.sum(valid) < 5:
            return

        price = window[valid]
        rsi_w = rsi_window[valid]

        idx_prev = len(price) // 2
        price_prev = np.max(price[:idx_prev]) if idx_prev > 0 else price[0]
        rsi_prev = np.max(rsi_w[:idx_prev]) if idx_prev > 0 else rsi_w[0]
        price_now = price[-1]
        rsi_now = rsi_w[-1]

        if price_now > price_prev and rsi_now < rsi_prev:
            signals.append({"type": "BEARISH_DIVERGENCE", "direction": "bearish", "strength": 0.7})

        price_prev_low = np.min(price[:idx_prev]) if idx_prev > 0 else price[0]
        rsi_prev_low = np.min(rsi_w[:idx_prev]) if idx_prev > 0 else rsi_w[0]

        if price_now < price_prev_low and rsi_now > rsi_prev_low:
            signals.append({"type": "BULLISH_DIVERGENCE", "direction": "bullish", "strength": 0.7})

    def _estimate_reliability(
        self, symbol: str, closep: np.ndarray, signal_count: int, volumes: np.ndarray
    ) -> float:
        """基于历史胜率估算信号可靠性（调用 memory.py）"""
        if self._memory is None:
            return 0.5

        recent_change = (closep[-1] - closep[-5]) / closep[-5] if len(closep) >= 5 else 0.0
        avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
        vol_change = (volumes[-1] - avg_vol) / avg_vol if avg_vol > 0 else 0.0

        features = [recent_change, vol_change, signal_count * 0.1]
        similar = self._memory.find_similar(features, k=5)

        if not similar:
            return 0.5

        win_rate = np.mean([s.outcome or 0.0 for s in similar])
        return round(min(1.0, max(0.1, win_rate)), 4)

    @staticmethod
    def _make_summary(signals: list) -> str:
        if not signals:
            return "无显著技术信号"
        bullish = [s for s in signals if s["direction"] == "bullish"]
        bearish = [s for s in signals if s["direction"] == "bearish"]
        parts = []
        if bullish:
            parts.append(f"看多信号{len(bullish)}个")
        if bearish:
            parts.append(f"看空信号{len(bearish)}个")
        return "，".join(parts) if parts else "信号交织"




"""
Market Trace V6.0 — 策略批量回测

对股票池中的每只股票，用历史数据跑全部策略，
计算夏普/最大回撤/胜率，按总分排序。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from loguru import logger

from backtest.runner import BacktestRunner

STRATEGIES = {
    "breakout": "强势突破",
    "oversold": "超跌反弹",
    "strength": "主力介入",
    "risk": "风险预警",
    "ma_golden_cross": "均线金叉",
    "volume_breakout": "放量突破",
    "rsi_reversal": "RSI反转",
}


def _evaluate_strategy(name: str, closes: list[float], highs: list[float],
                       volumes: list[float]) -> list[str]:
    """对单只股票的历史数据，逐 bar 评估某策略是否触发"""
    c = np.array(closes)
    h = np.array(highs)
    v = np.array(volumes)
    actions: list[str] = []
    min_len = {"breakout": 20, "oversold": 14, "strength": 5, "risk": 20,
               "ma_golden_cross": 20, "volume_breakout": 20, "rsi_reversal": 14}

    min_bars = min_len.get(name, 14)
    required_len = min_bars + 1  # need one extra for lookback

    for i in range(required_len, len(c) + 1):
        ci = c[:i]
        hi = h[:i] if len(h) >= i else h
        vi = v[:i] if len(v) >= i else v

        triggered = False

        if name == "breakout" and len(ci) >= 20:
            triggered = bool(ci[-1] > max(hi[-21:-1]) and vi[-1] > np.mean(vi[-21:-1]) * 1.5 and ci[-1] > ci[-2])
        elif name == "oversold" and len(ci) >= 14:
            rsi14 = _calc_rsi(ci, 14)
            triggered = bool(rsi14 < 35 and (ci[-1] - ci[-5]) / ci[-5] < -0.03)
        elif name == "strength" and len(ci) >= 5:
            triggered = bool(vi[-1] > np.mean(vi[-6:-1]) * 2 and ci[-1] > ci[-5])
        elif name == "risk" and len(ci) >= 20:
            rsi14 = _calc_rsi(ci, 14)
            triggered = bool(rsi14 > 70 and ci[-1] < ci[-20])
        elif name == "ma_golden_cross" and len(ci) >= 20:
            ma5 = _calc_ma(ci, 5)
            ma20 = _calc_ma(ci, 20)
            triggered = bool(ma5[-1] > ma20[-1] and ma5[-2] <= ma20[-2] and vi[-1] > np.mean(vi[-21:-1]) * 1.2)
        elif name == "volume_breakout" and len(ci) >= 20:
            triggered = bool(vi[-1] > np.mean(vi[-21:-1]) * 3 and (ci[-1] - ci[-5]) / ci[-5] > 0.05)
        elif name == "rsi_reversal" and len(ci) >= 14:
            rsi_now = _calc_rsi(ci, 14)
            rsi_prev = _calc_rsi(ci[:-1], 14) if len(ci) > 1 else 50
            triggered = bool(rsi_now < 30 and (rsi_now - rsi_prev) > 3)

        if triggered:
            actions.append("BUY")
        else:
            actions.append("HOLD")

    return actions


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-period-1:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    return float(100 - 100 / (1 + avg_gain / avg_loss))


def _calc_ma(closes: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        result[i] = np.mean(closes[i - period + 1:i + 1])
    return result


async def run_strategy_backtest(bus, config: dict, symbols: list[str] | None = None) -> dict[str, Any]:
    """对股票池跑所有策略回测，返回排序后的结果"""
    stock_pool = symbols or config.get("stock_pool", [])[:20]

    results: dict[str, dict[str, Any]] = {}

    for symbol in stock_pool:
        try:
            cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
            if not cached or len(cached) < 30:
                continue

            closes = [float(r["close"]) for r in cached]
            highs = [float(r["high"]) for r in cached]
            volumes = [float(r["volume"]) for r in cached]

            symbol_results: dict[str, Any] = {}

            for strategy, label in STRATEGIES.items():
                actions = _evaluate_strategy(strategy, closes, highs, volumes)
                if not actions or all(a == "HOLD" for a in actions):
                    continue

                runner = BacktestRunner(initial_capital=100000)
                buy_count = 0
                for i, action in enumerate(actions):
                    price = closes[i + _get_min_bars(strategy)]
                    result = runner.execute(action, price, confidence=0.7, reason=f"{label}信号")
                    if result and result.action == "BUY":
                        buy_count += 1
                    if result and result.action == "SELL" and buy_count > 0:
                        buy_count -= 1
                    if i >= len(actions) - 1 and runner.position.quantity > 0:
                        runner.execute("SELL", price, confidence=1.0, reason="回测结束平仓")

                bt_result = runner.finalize()
                score = (
                    bt_result.sharpe_ratio * 1.5
                    + bt_result.win_rate * 2
                    - bt_result.max_drawdown
                )
                symbol_results[strategy] = {
                    "label": label,
                    "sharpe": round(bt_result.sharpe_ratio, 4),
                    "max_drawdown_pct": round(bt_result.max_drawdown * 100, 2),
                    "win_rate_pct": round(bt_result.win_rate * 100, 2),
                    "total_trades": bt_result.total_trades,
                    "total_return_pct": round(bt_result.total_return * 100, 2),
                    "profit_factor": round(bt_result.profit_factor, 2),
                    "score": round(score, 2),
                }

            if symbol_results:
                results[symbol] = dict(sorted(symbol_results.items(), key=lambda x: -x[1]["score"]))

        except Exception as e:
            logger.warning("回测 {} 失败: {}", symbol, e)
            continue

    return results


def _get_min_bars(name: str) -> int:
    return {"breakout": 20, "oversold": 14, "strength": 5, "risk": 20,
            "ma_golden_cross": 20, "volume_breakout": 20, "rsi_reversal": 14}.get(name, 14)

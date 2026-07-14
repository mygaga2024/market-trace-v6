"""
Market Trace V6.0 — 专业策略回测框架
参数化策略、止损止盈、趋势过滤、网格搜索优化
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np
from loguru import logger

from backtest.runner import PortfolioRunner, BacktestResult
from core.strategies import STRATEGIES as STRATEGY_INFO, _calc_rsi, _calc_atr

# 保留 STRATEGIES labels 与 core/strategies.py 同步
STRATEGIES = {k: v["label"] for k, v in STRATEGY_INFO.items()}

# ── 趋势状态分类 ──


def _classify_trend(closes: np.ndarray, ma_fast: int = 20, ma_slow: int = 60) -> str:
    if len(closes) < ma_slow:
        return "unknown"
    fast = np.mean(closes[-ma_fast:])
    slow = np.mean(closes[-ma_slow:])
    if fast > slow * 1.02:
        return "up"
    elif fast < slow * 0.98:
        return "down"
    return "sideways"


# ── 各策略信号函数 ──

def signal_breakout(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                    lookback: int = 20, vol_mult: float = 1.5) -> tuple[str, float]:
    """突破策略: 价格突破N日高点 + 放量确认"""
    if len(closes) < lookback + 2:
        return "HOLD", 0
    is_breakout = closes[-1] > max(highs[-lookback - 1:-1]) if len(highs) >= lookback + 1 else False
    vol_confirmed = volumes[-1] > np.mean(volumes[-lookback - 1:-1]) * vol_mult if len(volumes) >= lookback + 1 else False
    if is_breakout and vol_confirmed and closes[-1] > closes[-2]:
        return "BUY", 0.25
    return "HOLD", 0


def signal_oversold(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                    rsi_period: int = 14, rsi_threshold: float = 30.0,
                    drop_pct: float = 0.03) -> tuple[str, float]:
    """超跌反弹: RSI低于阈值 + 短期超跌 + 当日反弹"""
    if len(closes) < max(rsi_period + 1, 6):
        return "HOLD", 0
    rsi = _calc_rsi(closes, rsi_period)
    drop = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 6 else 0
    reversal = closes[-1] > closes[-2]
    if rsi < rsi_threshold and drop < -drop_pct and reversal:
        return "BUY", 0.20
    return "HOLD", 0


def signal_strength(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                    vol_mult: float = 2.0, rise_pct: float = 0.02,
                    lookback: int = 20) -> tuple[str, float]:
    """主力介入: 巨量 + 短期上涨"""
    if len(closes) < max(lookback + 1, 6):
        return "HOLD", 0
    huge_vol = volumes[-1] > np.mean(volumes[-lookback - 1:-1]) * vol_mult
    rising = (closes[-1] - closes[-5]) / closes[-5] > rise_pct
    if huge_vol and rising:
        return "BUY", 0.30
    return "HOLD", 0


def signal_risk(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                rsi_period: int = 14, rsi_threshold: float = 70.0,
                lookback: int = 20) -> tuple[str, float]:
    """风险预警: RSI超买 + 低于N日前 + 下跌 + 放量"""
    if len(closes) < max(rsi_period + 1, lookback + 1):
        return "HOLD", 0
    rsi = _calc_rsi(closes, rsi_period)
    below_lookback = closes[-1] < closes[-lookback] if len(closes) >= lookback else False
    falling = closes[-1] < closes[-2]
    vol_up = volumes[-1] > np.mean(volumes[-21:-1]) * 1.2 if len(volumes) > 21 else True
    if rsi > rsi_threshold and below_lookback and falling and vol_up:
        return "SELL", 0
    return "HOLD", 0


def signal_ma_golden_cross(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                           ma_fast: int = 5, ma_slow: int = 20,
                           vol_mult: float = 1.2) -> tuple[str, float]:
    """均线金叉: MA快线上穿慢线 + 放量"""
    if len(closes) < ma_slow + 2:
        return "HOLD", 0
    fast_now = np.mean(closes[-ma_fast:])
    slow_now = np.mean(closes[-ma_slow:])
    fast_prev = np.mean(closes[-ma_fast - 1:-1])
    slow_prev = np.mean(closes[-ma_slow - 1:-1])
    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    vol_ok = volumes[-1] > np.mean(volumes[-ma_slow - 1:-1]) * vol_mult
    if crossed_up and vol_ok:
        return "BUY", 0.25
    # 死叉卖出
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "SELL", 0
    return "HOLD", 0


def signal_volume_breakout(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                           vol_mult: float = 3.0, rise_pct: float = 0.05) -> tuple[str, float]:
    """放量突破: 极端放量 + 急涨"""
    if len(closes) < 21:
        return "HOLD", 0
    extreme_vol = volumes[-1] > np.mean(volumes[-21:-1]) * vol_mult
    sharp_rise = (closes[-1] - closes[-5]) / closes[-5] > rise_pct if len(closes) >= 6 else False
    if extreme_vol and sharp_rise:
        return "BUY", 0.20
    return "HOLD", 0


def signal_rsi_reversal(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                        rsi_period: int = 14, rsi_threshold: float = 30.0,
                        delta_min: float = 3.0) -> tuple[str, float]:
    """RSI反转: RSI超卖 + 快速回升"""
    if len(closes) < rsi_period + 2:
        return "HOLD", 0
    rsi_now = _calc_rsi(closes, rsi_period)
    rsi_prev = _calc_rsi(closes[:-1], rsi_period)
    if rsi_now < rsi_threshold and (rsi_now - rsi_prev) > delta_min:
        return "BUY", 0.20
    return "HOLD", 0


# ── 信号函数注册表 ──

SIGNAL_FUNCTIONS: dict[str, Callable] = {
    "breakout": signal_breakout,
    "oversold": signal_oversold,
    "strength": signal_strength,
    "risk": signal_risk,
    "ma_golden_cross": signal_ma_golden_cross,
    "volume_breakout": signal_volume_breakout,
    "rsi_reversal": signal_rsi_reversal,
}

# ── 参数网格 ──

PARAM_GRIDS: dict[str, dict[str, list[Any]]] = {
    "breakout": {"lookback": [15, 20, 25], "vol_mult": [1.2, 1.5, 2.0]},
    "oversold": {"rsi_period": [7, 14], "rsi_threshold": [25.0, 30.0, 35.0], "drop_pct": [0.02, 0.03, 0.05]},
    "strength": {"vol_mult": [1.5, 2.0, 2.5], "rise_pct": [0.01, 0.02, 0.03]},
    "risk": {"rsi_period": [7, 14], "rsi_threshold": [65.0, 70.0, 75.0]},
    "ma_golden_cross": {"ma_fast": [5, 10], "ma_slow": [15, 20, 30], "vol_mult": [1.0, 1.2, 1.5]},
    "volume_breakout": {"vol_mult": [2.0, 2.5, 3.0], "rise_pct": [0.03, 0.05, 0.08]},
    "rsi_reversal": {"rsi_period": [7, 14], "rsi_threshold": [25.0, 30.0], "delta_min": [2.0, 3.0, 5.0]},
}


# ── 回测执行 ──

async def run_strategy_backtest(
    bus, config: dict, symbols: list[str] | None = None,
    active_strategies: list[str] | None = None,
    optimize: bool = False,
) -> dict[str, Any]:
    """对股票池跑策略回测，返回排序后的结果"""
    stock_pool = symbols or config.get("stock_pool", [])[:20]
    strategies_to_run = active_strategies if active_strategies is not None else list(STRATEGIES.keys())

    all_results: dict[str, dict[str, Any]] = {}

    for symbol in stock_pool:
        cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
        if not cached or len(cached) < 30:
            continue

        closes = np.array([float(r["close"]) for r in cached])
        highs = np.array([float(r["high"]) for r in cached])
        lows = np.array([float(r["low"]) for r in cached])
        volumes = np.array([float(r["volume"]) for r in cached])

        symbol_results: dict[str, Any] = {}

        for strategy in strategies_to_run:
            label = STRATEGIES.get(strategy, strategy)
            signal_fn = SIGNAL_FUNCTIONS.get(strategy)
            if not signal_fn:
                continue

            if optimize:
                best = await _optimize_strategy(
                    symbol, strategy, label, signal_fn, closes, highs, lows, volumes, cached
                )
                if best:
                    symbol_results[strategy] = best.to_dict()
            else:
                result = _run_single_backtest(
                    symbol, strategy, label, signal_fn, closes, highs, lows, volumes, cached
                )
                if result and result.total_trades > 0:
                    symbol_results[strategy] = result.to_dict()

        if symbol_results:
            all_results[symbol] = dict(
                sorted(symbol_results.items(), key=lambda x: -x[1]["score"])
            )

    return all_results


def _run_single_backtest(
    symbol: str, strategy: str, label: str,
    signal_fn: Callable, closes: np.ndarray, highs: np.ndarray,
    lows: np.ndarray, volumes: np.ndarray, bars: list[dict],
    params: dict[str, Any] | None = None,
    track_progress: bool = False,
) -> BacktestResult | None:
    """执行单策略单股票回测"""
    runner = PortfolioRunner(initial_capital=100000)
    min_bars = 25  # 需要足够数据计算指标

    for i in range(min_bars, len(bars)):
        bar = bars[i]
        bar_time = bar.get("time", bar.get("timestamp", str(i)))

        # 切片数据供策略使用
        ci = closes[:i + 1]
        hi = highs[:i + 1]
        li = lows[:i + 1]
        vi = volumes[:i + 1]

        # 推进 bar
        runner.step({"time": bar_time, "open": float(bar["open"]), "high": float(bar["high"]),
                      "low": float(bar["low"]), "close": float(bar["close"]),
                      "volume": float(bar["volume"])})

        # 检查退出条件
        exit_trade = runner.check_exits({"time": bar_time, "open": float(bar["open"]),
                                         "high": float(bar["high"]), "low": float(bar["low"]),
                                         "close": float(bar["close"]), "volume": float(bar["volume"])})

        # 生成信号
        kwargs = params.copy() if params else {}
        action, size_pct = signal_fn(ci, hi, vi, **kwargs)

        if action == "BUY" and runner.position.quantity == 0:
            runner.buy(bar, size_pct=size_pct, reason=f"{label}信号")
        elif action == "SELL" and runner.position.quantity > 0:
            runner.sell(bar, reason=f"{label}卖出信号")

    return runner.finalize(symbol=symbol, strategy=strategy, strategy_label=label, params=params)


async def _optimize_strategy(
    symbol: str, strategy: str, label: str,
    signal_fn: Callable, closes: np.ndarray, highs: np.ndarray,
    lows: np.ndarray, volumes: np.ndarray, bars: list[dict],
) -> BacktestResult | None:
    """网格搜索最优参数"""
    grid = PARAM_GRIDS.get(strategy, {})
    if not grid:
        return _run_single_backtest(symbol, strategy, label, signal_fn, closes, highs, lows, volumes, bars)

    keys = list(grid.keys())
    values = list(grid.values())
    best_result: BacktestResult | None = None
    best_params: dict[str, Any] = {}

    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        result = _run_single_backtest(
            symbol, strategy, label, signal_fn, closes, highs, lows, volumes, bars, params=params
        )
        if result and (best_result is None or result.score() > best_result.score()):
            best_result = result
            best_params = params

    if best_result:
        best_result.params = {"optimized": best_params, "grid_size": len(list(itertools.product(*values)))}
        logger.debug("{} {} 最优参数: {} 评分={:.2f}", symbol, label, best_params, best_result.score())

    return best_result


# ── 样本外验证（滚动窗口）──

async def run_rolling_backtest(
    bus, config: dict, symbol: str, strategy: str = "breakout",
    train_size: float = 0.7, step_size: int = 20,
) -> dict[str, Any]:
    """滚动窗口样本外验证：前train_size用于训练/选参，后续滚动回测"""
    from core.strategies import STRATEGIES as SINFO

    label = SINFO.get(strategy, {}).get("label", strategy)
    signal_fn = SIGNAL_FUNCTIONS.get(strategy)
    if not signal_fn:
        return {"error": f"策略不存在: {strategy}"}

    cached = await bus.cache_get(f"market:raw:{symbol}") if bus else None
    if not cached or len(cached) < 60:
        return {"error": f"{symbol} 数据不足(最少60条)"}

    closes = np.array([float(r["close"]) for r in cached])
    highs = np.array([float(r["high"]) for r in cached])
    lows = np.array([float(r["low"]) for r in cached])
    volumes = np.array([float(r["volume"]) for r in cached])

    n = len(cached)
    train_end = int(n * train_size)

    # 训练期优化参数
    train_bars = cached[:train_end]
    tc = closes[:train_end]
    th = highs[:train_end]
    tl = lows[:train_end]
    tv = volumes[:train_end]
    best = await _optimize_strategy(symbol, strategy, label, signal_fn, tc, th, tl, tv, train_bars)
    best_params = best.params.get("optimized", {}) if best else {}

    # 滚动窗口测试
    windows: list[dict] = []
    window_start = train_end
    while window_start + 30 <= n:
        window_end = min(n, window_start + 40)
        test_bars = cached[window_start:window_end]
        wc = closes[window_start:window_end]
        wh = highs[window_start:window_end]
        wl = lows[window_start:window_end]
        wv = volumes[window_start:window_end]

        result = _run_single_backtest(symbol, strategy, label, signal_fn, wc, wh, wl, wv, test_bars, params=best_params)
        if result:
            d = result.to_dict()
            d["window_start"] = window_start
            d["window_end"] = window_end
            windows.append(d)

        window_start += step_size

    # 汇总指标
    if not windows:
        return {"error": "无有效测试窗口", "symbol": symbol, "strategy": strategy}

    win_rates = [w["win_rate_pct"] for w in windows if w["total_trades"] > 0]
    sharpes = [w["sharpe_ratio"] for w in windows]
    returns = [w["total_return_pct"] for w in windows]

    return {
        "symbol": symbol, "strategy": strategy, "label": label,
        "train_bars": train_end, "test_bars": n - train_end,
        "total_windows": len(windows),
        "active_windows": len(win_rates),
        "best_params": best_params,
        "avg_win_rate": round(np.mean(win_rates), 2) if win_rates else 0,
        "avg_sharpe": round(np.mean(sharpes), 2),
        "avg_return": round(np.mean(returns), 2),
        "min_return": round(min(returns), 2),
        "max_return": round(max(returns), 2),
        "consistency": round(len([r for r in returns if r > 0]) / max(len(returns), 1), 2),
        "windows": windows,
    }

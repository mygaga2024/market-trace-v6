"""
Market Trace V6.0 — 统一策略定义

诊股、选股、回测共用同一套策略逻辑，消除重复维护。
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

STRATEGIES: dict[str, dict[str, Any]] = {
    "breakout": {
        "label": "强势突破",
        "params": {"lookback": 20, "vol_mult": 1.1},
        "rough_threshold": {"min_chg": 1.0, "min_price": 5.0},
        "check": None,  # filled below
    },
    "oversold": {
        "label": "超跌反弹",
        "params": {"rsi_period": 14, "rsi_threshold": 30.0, "drop_pct": 0.02},
        "rough_threshold": {"max_chg": -3.0},
        "check": None,
    },
    "strength": {
        "label": "主力介入",
        "params": {"vol_mult": 1.2, "rise_pct": 0.01, "lookback": 20},
        "rough_threshold": {"min_chg": 2.0},
        "check": None,
    },
    "risk": {
        "label": "风险预警",
        "params": {"rsi_period": 14, "rsi_threshold": 60.0, "lookback": 20},
        "rough_threshold": {"max_chg": -5.0},
        "check": None,
    },
    "ma_golden_cross": {
        "label": "均线金叉",
        "params": {"ma_fast": 5, "ma_slow": 20, "vol_mult": 1.0},
        "rough_threshold": {"min_chg": 0.5},
        "check": None,
    },
    "volume_breakout": {
        "label": "放量突破",
        "params": {"vol_mult": 1.5, "rise_pct": 0.02},
        "rough_threshold": {"min_chg": 3.0},
        "check": None,
    },
    "rsi_reversal": {
        "label": "RSI反转",
        "params": {"rsi_period": 14, "rsi_threshold": 30.0, "delta_min": 1.5},
        "rough_threshold": {"max_chg": -2.0},
        "check": None,
    },
}


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-period - 1:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return float(100 - 100 / (1 + avg_gain / avg_loss))


def _calc_ma(closes: np.ndarray, period: int) -> float:
    if len(closes) < period:
        return float(closes[-1])
    return float(np.mean(closes[-period:]))


def _calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """计算 ATR (Average True Range)，供诊股/风控/回测共用"""
    if len(closes) < period + 1:
        return float(np.mean(highs - lows)) if len(highs) > 0 else 0.0
    prev_close = closes[:-1]
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - prev_close),
        np.abs(lows[1:] - prev_close),
    ])
    return float(np.mean(tr[-period:]))


def _calc_ema(data: np.ndarray, period: int) -> np.ndarray:
    """计算指数移动平均，返回与输入等长的数组（前 period-1 为 NaN）"""
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
    result[period - 1] = np.mean(data[:period])
    alpha = 2.0 / (period + 1)
    for i in range(period, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _calc_macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算 MACD，返回最后一组值的 dict（供诊股用）"""
    if len(closes) < slow + signal:
        return {"dif": None, "dea": None, "histogram": None}
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    dif = ema_fast - ema_slow
    valid = dif[~np.isnan(dif)]
    if len(valid) < signal:
        return {"dif": None, "dea": None, "histogram": None}
    dea_partial = _calc_ema(valid, signal)
    dea = np.full(len(dif), np.nan)
    dea[len(dif) - len(dea_partial):] = dea_partial
    hist = 2 * (dif - dea)
    return {
        "dif": round(float(dif[-1]), 4) if not np.isnan(dif[-1]) else None,
        "dea": round(float(dea[-1]), 4) if not np.isnan(dea[-1]) else None,
        "histogram": round(float(hist[-1]), 4) if not np.isnan(hist[-1]) else None,
    }


def _calc_macd_vec(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, np.ndarray] | None:
    """计算 MACD，返回全量 ndarray（供 Agent 信号检测用）"""
    if len(closes) < slow + signal:
        return None
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    dif = ema_fast - ema_slow
    dea = _calc_ema(dif[~np.isnan(dif)], signal) if len(dif[~np.isnan(dif)]) > 0 else np.array([])
    if len(dea) == 0:
        return None
    dea_full = np.full(len(dif), np.nan)
    dea_start = len(dif) - len(dea)
    dea_full[dea_start:] = dea
    hist = 2 * (dif - dea_full)
    return {"dif": dif, "dea": dea_full, "hist": hist}


# ── 策略检测函数（返回 True/False）──

def check_breakout(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                   lookback: int = 20, vol_mult: float = 1.1) -> bool:
    if len(closes) < lookback + 2:
        return False
    return bool(closes[-1] > max(highs[-lookback - 1:-1])
                and volumes[-1] > np.mean(volumes[-lookback - 1:-1]) * vol_mult
                and closes[-1] > closes[-2])


def check_oversold(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                   rsi_period: int = 14, rsi_threshold: float = 30.0,
                   drop_pct: float = 0.02) -> bool:
    if len(closes) < max(rsi_period + 1, 6):
        return False
    rsi = _calc_rsi(closes, rsi_period)
    drop = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 6 else 0
    return bool(rsi < rsi_threshold and drop < -drop_pct)


def check_strength(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                   vol_mult: float = 1.2, rise_pct: float = 0.01,
                   lookback: int = 20) -> bool:
    if len(closes) < max(lookback + 1, 6):
        return False
    return bool(volumes[-1] > np.mean(volumes[-lookback - 1:-1]) * vol_mult
                and (closes[-1] - closes[-5]) / closes[-5] > rise_pct)


def check_risk(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
               rsi_period: int = 14, rsi_threshold: float = 60.0,
               lookback: int = 20) -> bool:
    if len(closes) < max(rsi_period + 1, lookback + 1):
        return False
    rsi = _calc_rsi(closes, rsi_period)
    return bool(rsi > rsi_threshold
                and closes[-1] < closes[-2]
                and volumes[-1] > np.mean(volumes[-lookback:-1]) * 1.1)


def check_ma_golden_cross(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                          ma_fast: int = 5, ma_slow: int = 20,
                          vol_mult: float = 1.0) -> bool:
    if len(closes) < ma_slow + 2:
        return False
    fast_now = np.mean(closes[-ma_fast:])
    slow_now = np.mean(closes[-ma_slow:])
    fast_prev = np.mean(closes[-ma_fast - 1:-1])
    slow_prev = np.mean(closes[-ma_slow - 1:-1])
    return bool(fast_prev <= slow_prev and fast_now > slow_now
                and volumes[-1] > np.mean(volumes[-ma_slow - 1:-1]) * vol_mult)


def check_volume_breakout(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                          vol_mult: float = 1.5, rise_pct: float = 0.02) -> bool:
    if len(closes) < 21:
        return False
    return bool(volumes[-1] > np.mean(volumes[-21:-1]) * vol_mult
                and (closes[-1] - closes[-5]) / closes[-5] > rise_pct)


def check_rsi_reversal(closes: np.ndarray, highs: np.ndarray, volumes: np.ndarray,
                       rsi_period: int = 14, rsi_threshold: float = 30.0,
                       delta_min: float = 1.5) -> bool:
    if len(closes) < rsi_period + 2:
        return False
    rsi_now = _calc_rsi(closes, rsi_period)
    rsi_prev = _calc_rsi(closes[:-1], rsi_period)
    return bool(rsi_now < rsi_threshold and (rsi_now - rsi_prev) > delta_min)


# 注册函数
_checks = {
    "breakout": check_breakout,
    "oversold": check_oversold,
    "strength": check_strength,
    "risk": check_risk,
    "ma_golden_cross": check_ma_golden_cross,
    "volume_breakout": check_volume_breakout,
    "rsi_reversal": check_rsi_reversal,
}
for name, fn in _checks.items():
    STRATEGIES[name]["check"] = fn

"""
Market Trace V6.0 — 仓位管理模块

凯利公式 / 等权重 / 风险平价
"""

from __future__ import annotations

import math
from typing import Optional


def kelly_criterion(win_prob: float, avg_win: float, avg_loss: float, fraction: float = 1.0) -> float:
    """
    凯利公式：f* = (p*b - q) / b
    
    Args:
        win_prob: 胜率 (0-1)
        avg_win: 平均盈利比例 (赔率 b > 0)
        avg_loss: 平均亏损比例 (> 0 取绝对值)
        fraction: Kelly 分数 (0-1)，保守用 0.25-0.5

    Returns:
        建议仓位比例 (0-1)，max 25% 单票
    """
    if avg_loss <= 0 or avg_win <= 0 or win_prob <= 0:
        return 0.0

    b = avg_win / avg_loss  # 盈亏比
    raw = (win_prob * b - (1 - win_prob)) / b

    result = max(0.0, min(raw * fraction, 0.25))
    return round(result, 4)


def equal_weight(num_stocks: int) -> float:
    """等权重分配"""
    if num_stocks <= 0:
        return 0.0
    return round(min(1.0 / num_stocks, 0.25), 4)


def risk_parity(volatilities: list[float]) -> list[float]:
    """
    风险平价：权重与波动率倒数成正比
    
    Args:
        volatilities: 每只股票的年化波动率列表

    Returns:
        每只股票的建议权重列表（总和=1）
    """
    if not volatilities:
        return []

    if any(v <= 0 for v in volatilities):
        return None  # 波动率必须为正, 0/负值 clamp 会产生失真权重

    inv_vol = [1.0 / v for v in volatilities]
    total = sum(inv_vol)
    if total <= 0:
        return [1.0 / len(volatilities)] * len(volatilities)

    return [round(w / total, 4) for w in inv_vol]


def suggest_position(
    method: str = "kelly",
    capital: float = 100000,
    price: float = 10.0,
    win_prob: float = 0.5,
    avg_win: float = 0.03,
    avg_loss: float = 0.02,
    num_stocks: int = 5,
    kelly_fraction: float = 0.5,
    max_pct: float = 0.25,
) -> dict:
    """
    综合仓位建议

    Returns:
        {
            "method": str,           # 选用的仓位方法
            "position_pct": float,   # 建议仓位比例
            "shares": int,           # 建议股数（100股整数倍）
            "amount": float,         # 建议金额
            "detail": str,           # 计算说明
        }
    """
    if method == "kelly":
        pct = kelly_criterion(win_prob, avg_win, avg_loss, kelly_fraction)
        detail = f"凯利公式: F={kelly_fraction}×, 胜率={win_prob:.0%}, 盈亏比={avg_win/avg_loss:.1f}"
    elif method == "equal":
        pct = equal_weight(num_stocks)
        detail = f"等权重: {num_stocks}只标的, 每只{pct:.1%}"
    elif method == "parity":
        pct = min(1.0 / max(num_stocks, 1), max_pct)
        detail = f"风险平价: {num_stocks}只标的, 单票上限{max_pct:.0%}"
    else:
        pct = 0.1
        detail = "默认 10% 仓位"

    amount = capital * pct
    lot = 100
    shares = int(amount / price / lot) * lot if price > 0 else 0
    shares = max(shares, 100) if pct > 0 and shares < 100 else shares

    return {
        "method": method,
        "position_pct": round(pct, 4),
        "shares": shares,
        "amount": round(price * shares, 2),
        "detail": detail,
    }

"""
Market Trace V6.0 — 策略回测引擎
模拟交易执行、持仓跟踪、计算夏普比率/最大回撤/胜率等核心指标
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
from loguru import logger


@dataclass
class Trade:
    """单笔交易记录"""
    timestamp: datetime
    action: str
    price: float
    quantity: int
    commission: float = 0.0
    slippage_cost: float = 0.0
    reason: str = ""
    decision_id: str = ""

    @property
    def value(self) -> float:
        return self.price * self.quantity


@dataclass
class BacktestPosition:
    """持仓"""
    symbol: str = ""
    quantity: int = 0
    avg_cost: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.avg_cost


@dataclass
class BacktestResult:
    """回测结果"""
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_profit_per_trade: float = 0.0
    profit_factor: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return * 100, 2),
            "annual_return_pct": round(self.annual_return * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "max_drawdown_duration": self.max_drawdown_duration,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_profit_per_trade": round(self.avg_profit_per_trade, 2),
            "profit_factor": round(self.profit_factor, 2),
        }


class BacktestRunner:
    """
    策略回测引擎

    纯事件驱动：根据市场数据(价格)和决策(action)执行模拟交易，
    计算标准量化指标。
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.001,
        risk_free_rate: float = 0.03,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.risk_free_rate = risk_free_rate

        self.capital = initial_capital
        self.position = BacktestPosition()
        self.trades: list[Trade] = []
        self.equity_curve: list[dict[str, Any]] = []
        self._peak_equity = initial_capital
        self._drawdown_start: Optional[int] = None
        self._bar_index = 0

    def reset(self) -> None:
        """重置回测状态"""
        self.capital = self.initial_capital
        self.position = BacktestPosition()
        self.trades.clear()
        self.equity_curve.clear()
        self._peak_equity = self.initial_capital
        self._drawdown_start = None
        self._bar_index = 0

    def execute(self, action: str, price: float, confidence: float = 0.5, reason: str = "", decision_id: str = "") -> Optional[Trade]:
        """
        执行交易

        Args:
            action: BUY / SELL / HOLD / WAIT
            price: 当前价格
            confidence: 决策置信度（影响仓位比例）
            reason: 决策理由
            decision_id: 决策 ID

        Returns:
            Trade 对象或 None (HOLD/WAIT 时)
        """
        if action in ("HOLD", "WAIT"):
            self._record_equity(self._bar_index, price)
            self._bar_index += 1
            return None

        trade = None

        if action == "BUY" and self.capital > 0:
            trade = self._execute_buy(price, confidence, reason, decision_id)
        elif action == "SELL" and self.position.quantity > 0:
            trade = self._execute_sell(price, reason, decision_id)

        self._bar_index += 1
        return trade

    def _execute_buy(self, price: float, confidence: float, reason: str, decision_id: str) -> Trade:
        exec_price = price * (1 + self.slippage)
        allocation = min(confidence, 0.95)
        available = self.capital * allocation
        quantity = int(available / exec_price / 100) * 100

        if quantity <= 0:
            return Trade(
                timestamp=datetime.now(timezone.utc), action="BUY",
                price=exec_price, quantity=0, reason="资金不足", decision_id=decision_id,
            )

        cost = quantity * exec_price
        commission = cost * self.commission_rate
        total_cost = cost + commission

        if total_cost > self.capital:
            quantity = int((self.capital * 0.95) / exec_price / 100) * 100
            cost = quantity * exec_price
            commission = cost * self.commission_rate
            total_cost = cost + commission

        if quantity <= 0:
            return Trade(datetime.now(timezone.utc), "BUY", exec_price, 0, reason="资金不足", decision_id=decision_id)

        self.capital -= total_cost
        old_qty = self.position.quantity
        old_cost = self.position.avg_cost
        self.position.quantity += quantity
        if self.position.quantity > 0:
            self.position.avg_cost = (old_qty * old_cost + total_cost) / self.position.quantity

        trade = Trade(
            timestamp=datetime.now(timezone.utc), action="BUY", price=exec_price,
            quantity=quantity, commission=commission, slippage_cost=cost - quantity * price,
            reason=reason, decision_id=decision_id,
        )
        self.trades.append(trade)
        self._record_equity(self._bar_index, price)

        logger.debug("回测买入: qty={}, price={:.2f}, cost={:.2f}, capital={:.2f}", quantity, exec_price, total_cost, self.capital)
        return trade

    def _execute_sell(self, price: float, reason: str, decision_id: str) -> Trade:
        exec_price = price * (1 - self.slippage)
        quantity = self.position.quantity

        revenue = quantity * exec_price
        commission = revenue * self.commission_rate
        net_revenue = revenue - commission

        self.capital += net_revenue
        self.position = BacktestPosition()

        trade = Trade(
            timestamp=datetime.now(timezone.utc), action="SELL", price=exec_price,
            quantity=quantity, commission=commission, slippage_cost=quantity * price - revenue,
            reason=reason, decision_id=decision_id,
        )
        self.trades.append(trade)
        self._record_equity(self._bar_index, price)

        logger.debug("回测卖出: qty={}, price={:.2f}, revenue={:.2f}, capital={:.2f}", quantity, exec_price, net_revenue, self.capital)
        return trade

    def _record_equity(self, bar: int, price: float) -> None:
        equity = self.capital + self.position.quantity * price
        self.equity_curve.append({"bar": bar, "equity": equity, "price": price})

    def finalize(self) -> BacktestResult:
        """计算最终回测指标"""
        if not self.equity_curve:
            return BacktestResult(initial_capital=self.initial_capital)

        equities = np.array([e["equity"] for e in self.equity_curve])
        final_equity = equities[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        n_bars = len(equities)
        trading_days = max(n_bars, 1)
        years = trading_days / 252
        annual_return = (1 + total_return) ** (1 / max(years, 0.01)) - 1

        returns = np.diff(equities) / equities[:-1]
        sharpe = 0.0
        if len(returns) > 1 and np.std(returns) > 0:
            excess = np.mean(returns) - self.risk_free_rate / 252
            sharpe = excess / np.std(returns) * np.sqrt(252)

        peak = np.maximum.accumulate(equities)
        drawdowns = (peak - equities) / peak
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        dd_duration = 0
        current_duration = 0
        for dd in drawdowns:
            if dd > 0:
                current_duration += 1
                dd_duration = max(dd_duration, current_duration)
            else:
                current_duration = 0

        buy_trades = [t for t in self.trades if t.action == "BUY"]
        sell_trades = [t for t in self.trades if t.action == "SELL"]
        total_trades = len(sell_trades)

        profits: list[float] = []
        for i in range(min(len(buy_trades), len(sell_trades))):
            buy_val = buy_trades[i].value
            sell_val = sell_trades[i].value
            profits.append(sell_val - buy_val - buy_trades[i].commission - sell_trades[i].commission)

        winning = [p for p in profits if p > 0]
        losing = [p for p in profits if p <= 0]
        win_rate = len(winning) / max(total_trades, 1)
        avg_profit = np.mean(profits) if profits else 0
        total_profit = sum(winning) if winning else 0
        total_loss = abs(sum(losing)) if losing else 0
        profit_factor = total_profit / max(total_loss, 1)

        return BacktestResult(
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            max_drawdown_duration=dd_duration,
            win_rate=win_rate,
            total_trades=total_trades,
            winning_trades=len(winning),
            losing_trades=len(losing),
            avg_profit_per_trade=avg_profit,
            profit_factor=profit_factor,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )

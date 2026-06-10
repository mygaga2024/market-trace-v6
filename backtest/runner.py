"""
Market Trace V6.0 — 专业回测引擎
多仓位组合、止损止盈、真实时间戳、基准对比、参数优化
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
from loguru import logger


# ── 订单/交易/持仓 ──

@dataclass
class Trade:
    timestamp: datetime
    action: str  # BUY / SELL
    price: float
    quantity: int
    commission: float = 0.0
    slippage_cost: float = 0.0
    reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0

    @property
    def value(self) -> float:
        return self.price * self.quantity


@dataclass
class Position:
    quantity: int = 0
    avg_cost: float = 0.0
    entry_time: Optional[str] = None
    highest_price: float = 0.0
    stop_loss_price: float = 0.0

    @property
    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    def add(self, qty: int, cost: float, bar_time: str) -> None:
        if self.quantity == 0:
            self.avg_cost = cost / qty
            self.quantity = qty
            self.entry_time = bar_time
            self.highest_price = cost / qty
            self.stop_loss_price = 0.0
        else:
            total_qty = self.quantity + qty
            self.avg_cost = (self.cost_basis + cost) / total_qty
            self.quantity = total_qty

    def reduce(self, qty: int) -> float:
        sold_cost = qty * self.avg_cost
        self.quantity -= qty
        if self.quantity == 0:
            self.avg_cost = 0.0
            self.entry_time = None
            self.highest_price = 0.0
            self.stop_loss_price = 0.0
        return sold_cost


@dataclass
class BacktestResult:
    """单支股票单策略回测结果"""
    symbol: str = ""
    strategy: str = ""
    strategy_label: str = ""

    # --- 策略表现 ---
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_profit_per_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    total_commission: float = 0.0
    avg_hold_bars: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # --- 基准对比 ---
    benchmark_return: float = 0.0
    benchmark_sharpe: float = 0.0
    benchmark_max_dd: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    information_ratio: float = 0.0

    # --- 参数 ---
    params: dict[str, Any] = field(default_factory=dict)

    # --- 曲线数据 ---
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    benchmark_curve: list[dict[str, Any]] = field(default_factory=list)
    drawdown_curve: list[dict[str, Any]] = field(default_factory=list)
    trade_markers: list[dict[str, Any]] = field(default_factory=list)
    period_returns: list[dict[str, Any]] = field(default_factory=list)

    def score(self) -> float:
        """综合评分"""
        s = 0.0
        s += self.sharpe_ratio * 1.5
        s += self.win_rate * 2.0
        s -= self.max_drawdown * 2.0
        s += self.profit_factor * 0.5
        s += self.total_return * 3.0
        if self.total_trades >= 10:
            s += 1.0
        return round(s, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return * 100, 2),
            "annual_return_pct": round(self.annual_return * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "max_drawdown_duration": self.max_drawdown_duration,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_profit_per_trade": round(self.avg_profit_per_trade, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "total_commission": round(self.total_commission, 2),
            "avg_hold_bars": round(self.avg_hold_bars, 1),
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "benchmark_return_pct": round(self.benchmark_return * 100, 2),
            "benchmark_sharpe": round(self.benchmark_sharpe, 4),
            "benchmark_max_dd_pct": round(self.benchmark_max_dd * 100, 2),
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "information_ratio": round(self.information_ratio, 4),
            "params": self.params,
            "score": self.score(),
            "equity_curve": self.equity_curve,
            "benchmark_curve": self.benchmark_curve,
            "drawdown_curve": self.drawdown_curve,
            "trade_markers": self.trade_markers,
            "period_returns": self.period_returns,
        }


# ── 回测引擎 ──

class PortfolioRunner:
    """多仓位组合回测引擎"""

    def __init__(
        self,
        initial_capital: float = 100_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.001,
        risk_free_rate: float = 0.03,
        max_position_pct: float = 0.30,
        stop_loss_atr_mult: float = 2.0,
        take_profit_pct: float = 0.15,
        trailing_stop_pct: float = 0.05,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.risk_free_rate = risk_free_rate
        self.max_position_pct = max_position_pct
        self.stop_loss_atr_mult = stop_loss_atr_mult
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct

        self.capital = initial_capital
        self.position = Position()
        self.trades: list[Trade] = []
        self.equity_curve: list[dict[str, Any]] = []
        self.benchmark_curve: list[dict[str, Any]] = []
        self.drawdown_curve: list[dict[str, Any]] = []
        self.trade_markers: list[dict[str, Any]] = []
        self._peak_equity = initial_capital
        self._drawdown_start: int = 0
        self._current_duration = 0

        self._open_trade: Optional[Trade] = None
        self._bars_held = 0
        self._hold_durations: list[int] = []
        self._consecutive_wins = 0
        self._consecutive_losses = 0
        self._max_consecutive_wins = 0
        self._max_consecutive_losses = 0
        self._benchmark_initial_price: float = 0.0

    def reset(self) -> None:
        self.capital = self.initial_capital
        self.position = Position()
        self.trades.clear()
        self.equity_curve.clear()
        self.benchmark_curve.clear()
        self.drawdown_curve.clear()
        self.trade_markers.clear()
        self._peak_equity = self.initial_capital
        self._drawdown_start = 0
        self._current_duration = 0
        self._open_trade = None
        self._bars_held = 0
        self._hold_durations.clear()
        self._consecutive_wins = 0
        self._consecutive_losses = 0
        self._max_consecutive_wins = 0
        self._max_consecutive_losses = 0
        self._benchmark_initial_price = 0.0

    def step(self, bar: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        执行一个 bar 的推进。
        bar: {"time": str, "open": float, "high": float, "low": float, "close": float, "volume": float}

        返回该 bar 的权益快照，或 None（无持仓无交易时）
        """
        t = bar.get("time", "")
        close = float(bar["close"])
        high = float(bar.get("high", close))
        low = float(bar.get("low", close))
        volume = float(bar.get("volume", 0))

        # 基准初始化
        if self._benchmark_initial_price == 0.0:
            self._benchmark_initial_price = close

        # 如果有持仓，跟踪最高价
        if self.position.quantity > 0:
            self.position.highest_price = max(self.position.highest_price, high)
            self._bars_held += 1

        # 记录权益曲线
        equity = self.capital + self.position.market_value(close)
        self.equity_curve.append({
            "time": t, "equity": round(equity, 2),
            "capital": round(self.capital, 2), "position_value": round(self.position.market_value(close), 2),
            "close": close,
        })
        self.benchmark_curve.append({
            "time": t,
            "value": round(self.initial_capital * close / self._benchmark_initial_price, 2),
        })

        # 回撤
        if equity > self._peak_equity:
            self._peak_equity = equity
            self._current_duration = 0
        else:
            self._current_duration += 1
        dd = (self._peak_equity - equity) / max(self._peak_equity, 1)
        self.drawdown_curve.append({"time": t, "drawdown": round(dd, 4)})

        snapshot = {
            "time": t, "close": close, "equity": equity,
            "capital": self.capital, "position": self.position.quantity,
            "drawdown": round(dd, 4),
        }

        return snapshot

    def buy(self, bar: dict[str, Any], size_pct: float = 0.3, reason: str = "") -> Optional[Trade]:
        """买入信号"""
        close = float(bar["close"])
        t = bar.get("time", datetime.now(timezone.utc).isoformat())

        if self.position.quantity > 0:
            return None  # 单仓位模式，不重复买入

        exec_price = close * (1 + self.slippage)
        allocation = min(size_pct, self.max_position_pct)
        available = self.capital * allocation
        quantity = int(available / exec_price / 100) * 100

        if quantity <= 0:
            return None

        cost = quantity * exec_price
        commission = cost * self.commission_rate
        total_cost = cost + commission

        if total_cost > self.capital * self.max_position_pct:
            return None

        self.capital -= total_cost
        self.position.add(quantity, total_cost, t)
        self._bars_held = 0

        trade = Trade(
            timestamp=datetime.now(timezone.utc), action="BUY",
            price=exec_price, quantity=quantity, commission=commission,
            slippage_cost=cost - quantity * close, reason=reason,
        )
        self.trades.append(trade)
        self._open_trade = trade

        self.trade_markers.append({
            "time": t, "type": "buy", "price": round(exec_price, 2),
            "quantity": quantity, "reason": reason,
        })

        return trade

    def sell(self, bar: dict[str, Any], reason: str = "signal") -> Optional[Trade]:
        """卖出信号"""
        close = float(bar["close"])
        t = bar.get("time", datetime.now(timezone.utc).isoformat())

        if self.position.quantity <= 0:
            return None

        exec_price = close * (1 - self.slippage)
        quantity = self.position.quantity

        revenue = quantity * exec_price
        commission = revenue * self.commission_rate
        net_revenue = revenue - commission

        sold_cost = self.position.reduce(quantity)
        pnl = net_revenue - sold_cost
        pnl_pct = pnl / sold_cost if sold_cost > 0 else 0.0
        self.capital += net_revenue

        self._hold_durations.append(self._bars_held)

        if pnl > 0:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
            self._max_consecutive_wins = max(self._max_consecutive_wins, self._consecutive_wins)
        else:
            self._consecutive_losses += 1
            self._consecutive_wins = 0
            self._max_consecutive_losses = max(self._max_consecutive_losses, self._consecutive_losses)

        trade = Trade(
            timestamp=datetime.now(timezone.utc), action="SELL",
            price=exec_price, quantity=quantity, commission=commission,
            slippage_cost=quantity * close - revenue,
            reason=reason, pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 4),
        )
        self.trades.append(trade)

        self.trade_markers.append({
            "time": t, "type": "sell", "price": round(exec_price, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct * 100, 2), "reason": reason,
        })

        self._open_trade = None
        return trade

    def check_exits(self, bar: dict[str, Any]) -> Optional[Trade]:
        """检查止盈止损条件（每 bar 调用）"""
        if self.position.quantity <= 0:
            return None

        close = float(bar["close"])
        low = float(bar.get("low", close))
        avg_cost = self.position.avg_cost
        highest = self.position.highest_price

        # 止损: 固定百分比
        stop_loss = avg_cost * (1 - self.trailing_stop_pct)
        if low <= stop_loss:
            return self.sell(bar, reason=f"止损 -{self.trailing_stop_pct*100:.0f}%")

        # 浮动止盈: 从最高点回落
        if highest > avg_cost * (1 + self.take_profit_pct):
            trailing_stop = highest * (1 - self.trailing_stop_pct)
            if low <= trailing_stop:
                return self.sell(bar, reason=f"移动止盈 最高{highest:.2f}")

        return None

    def finalize(self, symbol: str = "", strategy: str = "", strategy_label: str = "",
                 params: dict[str, Any] | None = None) -> BacktestResult:
        """计算最终指标"""
        # 强制平仓
        if self.position.quantity > 0 and len(self.equity_curve) > 0:
            last_close = float(self.equity_curve[-1].get("close", self.equity_curve[-1].get("equity", 0)))
            self.sell(
                {"time": self.equity_curve[-1].get("time", ""), "close": last_close},
                reason="回测结束平仓",
            )

        result = BacktestResult(
            symbol=symbol, strategy=strategy, strategy_label=strategy_label,
            initial_capital=self.initial_capital, params=params or {},
            equity_curve=self.equity_curve,
            benchmark_curve=self.benchmark_curve,
            drawdown_curve=self.drawdown_curve,
            trade_markers=self.trade_markers,
        )

        if not self.equity_curve:
            return result

        equities = np.array([e["equity"] for e in self.equity_curve])
        final_equity = equities[-1]
        result.final_equity = final_equity
        result.total_return = (final_equity - self.initial_capital) / self.initial_capital

        n_bars = len(equities)
        years = max(n_bars / 252, 0.02)
        result.annual_return = (1 + result.total_return) ** (1 / years) - 1

        # 日收益率
        daily_returns = np.diff(equities) / np.maximum(equities[:-1], 1)
        if len(daily_returns) > 1 and np.std(daily_returns) > 1e-10:
            excess = np.mean(daily_returns) - self.risk_free_rate / 252
            result.sharpe_ratio = float(excess / np.std(daily_returns) * np.sqrt(252))

        # Sortino: 只考虑下行波动
        if len(daily_returns) > 1:
            downside = daily_returns[daily_returns < 0]
            if len(downside) > 1 and np.std(downside) > 1e-10:
                result.sortino_ratio = float(
                    (np.mean(daily_returns) - self.risk_free_rate / 252)
                    / np.std(downside) * np.sqrt(252)
                )

        # 最大回撤
        peak = np.maximum.accumulate(equities)
        drawdowns = (peak - equities) / np.maximum(peak, 1)
        result.max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # 回撤持续期
        dd_max_duration = 0
        cur = 0
        for dd in drawdowns:
            if dd > 0.001:
                cur += 1
                dd_max_duration = max(dd_max_duration, cur)
            else:
                cur = 0
        result.max_drawdown_duration = dd_max_duration

        # Calmar
        if result.max_drawdown > 0.001 and years > 0:
            result.calmar_ratio = float(result.annual_return / result.max_drawdown)

        # 交易统计
        sell_trades = [t for t in self.trades if t.action == "SELL"]
        result.total_trades = len(sell_trades)

        if sell_trades:
            winning = [t for t in sell_trades if t.pnl > 0]
            losing = [t for t in sell_trades if t.pnl <= 0]
            result.winning_trades = len(winning)
            result.losing_trades = len(losing)
            result.win_rate = len(winning) / max(result.total_trades, 1)

            profits = [t.pnl for t in sell_trades]
            result.avg_profit_per_trade = float(np.mean(profits))
            result.avg_win = float(np.mean([t.pnl for t in winning])) if winning else 0.0
            result.avg_loss = float(np.mean([t.pnl for t in losing])) if losing else 0.0

            total_profit = sum(t.pnl for t in winning) if winning else 0.0
            total_loss = abs(sum(t.pnl for t in losing)) if losing else 0.0
            result.profit_factor = total_profit / max(total_loss, 1)

        result.total_commission = sum(t.commission for t in self.trades)
        result.avg_hold_bars = float(np.mean(self._hold_durations)) if self._hold_durations else 0.0
        result.max_consecutive_wins = self._max_consecutive_wins
        result.max_consecutive_losses = self._max_consecutive_losses

        # 基准
        if len(self.benchmark_curve) > 1:
            bench_vals = np.array([b["value"] for b in self.benchmark_curve])
            result.benchmark_return = (bench_vals[-1] - self.initial_capital) / self.initial_capital
            bench_ret = np.diff(bench_vals) / np.maximum(bench_vals[:-1], 1)
            if len(bench_ret) > 1 and np.std(bench_ret) > 1e-10:
                result.benchmark_sharpe = float(
                    (np.mean(bench_ret) - self.risk_free_rate / 252) / np.std(bench_ret) * np.sqrt(252)
                )
            bench_peak = np.maximum.accumulate(bench_vals)
            bench_dd = (bench_peak - bench_vals) / np.maximum(bench_peak, 1)
            result.benchmark_max_dd = float(np.max(bench_dd))

            # Alpha / Beta / IR via CAPM regression
            if len(daily_returns) > 2 and len(bench_ret) > 2:
                min_len = min(len(daily_returns), len(bench_ret))
                rp = daily_returns[-min_len:]
                rb = bench_ret[-min_len:]
                cov = np.cov(rp, rb)
                if cov.shape == (2, 2) and cov[0, 0] > 1e-10 and cov[1, 1] > 1e-10:
                    result.beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 1e-10 else 0.0
                    alpha_daily = np.mean(rp) - result.beta * np.mean(rb)
                    result.alpha = float(alpha_daily * 252)
                    tracking_error = np.std(rp - rb)
                    result.information_ratio = float(
                        (np.mean(rp) - np.mean(rb)) / tracking_error * np.sqrt(252)
                    ) if tracking_error > 1e-10 else 0.0

        # 周期收益率
        result.period_returns = self._calc_period_returns()

        return result

    def _calc_period_returns(self) -> list[dict[str, Any]]:
        """计算周/月收益率"""
        if not self.equity_curve:
            return []
        periods: list[dict[str, Any]] = []
        try:
            equities = np.array([e["equity"] for e in self.equity_curve])
            times = [e["time"] for e in self.equity_curve]
            if len(times) < 5:
                return []
            # 按周聚合
            week_key = None
            week_start_val = equities[0]
            for i, t in enumerate(times):
                try:
                    wk = t[:7] if len(t) >= 7 else t[:4]
                except Exception:
                    wk = t[:4]
                if wk != week_key:
                    if week_key is not None:
                        ret = (equities[i - 1] - week_start_val) / max(week_start_val, 1)
                        periods.append({"period": week_key, "type": "week", "return": round(float(ret) * 100, 2)})
                    week_key = wk
                    week_start_val = equities[i]
        except Exception:
            pass
        return periods

"""
Market Trace V6.0 — 纸上交易模块
模拟账户、虚拟持仓、真实P&L追踪、策略实战检验
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from loguru import logger


@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    action: str  # BUY / SELL
    quantity: int
    price: float
    timestamp: datetime
    filled: bool = True
    reason: str = ""
    commission: float = 0.0

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass
class PaperPosition:
    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    entry_time: Optional[datetime] = None
    total_commission: float = 0.0

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def unrealized_pnl(self, current_price: float) -> float:
        return self.market_value(current_price) - self.cost_basis

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.cost_basis <= 0:
            return 0.0
        return (self.market_value(current_price) - self.cost_basis) / self.cost_basis

    def add(self, quantity: int, price: float, timestamp: datetime, commission: float = 0.0) -> None:
        """买入增仓"""
        cost = quantity * price
        if self.quantity == 0:
            self.avg_cost = price
            self.quantity = quantity
            self.entry_time = timestamp
        else:
            total_cost = self.cost_basis + cost
            self.quantity += quantity
            self.avg_cost = total_cost / self.quantity
        self.total_commission += commission

    def reduce(self, quantity: int) -> None:
        """卖出减仓"""
        self.quantity = max(0, self.quantity - quantity)
        if self.quantity == 0:
            self.avg_cost = 0.0
            self.entry_time = None


@dataclass
class PaperAccount:
    account_id: str
    initial_capital: float = 100_000
    capital: float = 100_000
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    orders: list[PaperOrder] = field(default_factory=list)
    equity_history: list[dict] = field(default_factory=list)

    @property
    def total_equity(self) -> float:
        """成本法估值（不含未实现盈亏），市价估值请用 mark_to_market()"""
        return self.capital + sum(p.cost_basis for p in self.positions.values())

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.initial_capital if self.initial_capital > 0 else 0.0

    def can_buy(self, price: float, quantity: int) -> bool:
        cost = price * quantity
        commission = cost * 0.0003
        return (cost + commission) <= self.capital * 0.95

    def execute_buy(self, symbol: str, price: float, quantity: int, reason: str = "") -> Optional[PaperOrder]:
        if quantity <= 0:
            return None
        cost = price * quantity
        commission = cost * 0.0003
        total = cost + commission

        if total > self.capital * 0.95:
            return None

        self.capital -= total
        order = PaperOrder(
            order_id=f"paper_{symbol}_{int(datetime.now(timezone.utc).timestamp())}",
            symbol=symbol, action="BUY", quantity=quantity, price=price,
            timestamp=datetime.now(timezone.utc), reason=reason, commission=commission,
        )
        self.orders.append(order)

        if symbol not in self.positions:
            self.positions[symbol] = PaperPosition(symbol=symbol)
        pos = self.positions[symbol]
        pos.add(quantity, price, order.timestamp, commission)

        return order

    def execute_sell(self, symbol: str, price: float, quantity: int = 0, reason: str = "") -> Optional[PaperOrder]:
        if symbol not in self.positions:
            return None
        pos = self.positions[symbol]
        qty = quantity if quantity > 0 else pos.quantity
        if qty > pos.quantity:
            qty = pos.quantity
        if qty <= 0:
            return None

        revenue = price * qty
        commission = revenue * 0.0003
        net = revenue - commission
        self.capital += net

        order = PaperOrder(
            order_id=f"paper_{symbol}_{int(datetime.now(timezone.utc).timestamp())}",
            symbol=symbol, action="SELL", quantity=qty, price=price,
            timestamp=datetime.now(timezone.utc), reason=reason, commission=commission,
        )
        self.orders.append(order)
        pos.reduce(qty)
        if pos.quantity == 0:
            del self.positions[symbol]

        return order

    def get_summary(self) -> dict:
        trades = [o for o in self.orders if o.action in ("BUY", "SELL")]
        return {
            "account_id": self.account_id,
            "initial_capital": self.initial_capital,
            "capital": round(self.capital, 2),
            "total_equity": round(self.total_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct * 100, 2),
            "position_count": len(self.positions),
            "positions": [
                {
                    "symbol": p.symbol, "quantity": p.quantity,
                    "avg_cost": round(p.avg_cost, 2),
                    "cost_basis": round(p.cost_basis, 2),
                    "entry_time": p.entry_time.isoformat() if p.entry_time else None,
                }
                for p in self.positions.values()
            ],
            "total_orders": len(self.orders),
            "total_trades": len(trades),
            "recent_orders": [
                {
                    "order_id": o.order_id, "symbol": o.symbol,
                    "action": o.action, "quantity": o.quantity,
                    "price": round(o.price, 2), "reason": o.reason,
                    "timestamp": o.timestamp.isoformat(),
                }
                for o in self.orders[-20:]
            ],
        }


class PaperTradeManager:
    """纸上交易管理器：多账户、P&L追踪、策略绩效"""

    _PERSIST_PATH = Path("data/paper_accounts.json")

    def __init__(self, bus):
        self.bus = bus
        self._accounts: dict[str, PaperAccount] = {}
        self._default_account: Optional[PaperAccount] = None
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            if self._PERSIST_PATH.exists():
                data = json.loads(self._PERSIST_PATH.read_text("utf-8"))
                for acct_id, acct_data in data.get("accounts", {}).items():
                    acct = PaperAccount(
                        account_id=acct_id,
                        initial_capital=acct_data.get("initial_capital", 100_000),
                        capital=acct_data.get("capital", 100_000),
                    )
                    for sym, pos_data in acct_data.get("positions", {}).items():
                        pos = PaperPosition(
                            symbol=sym,
                            quantity=pos_data.get("quantity", 0),
                            avg_cost=pos_data.get("avg_cost", 0.0),
                            entry_time=datetime.fromisoformat(pos_data["entry_time"]) if pos_data.get("entry_time") else None,
                            total_commission=pos_data.get("total_commission", 0.0),
                        )
                        acct.positions[sym] = pos
                    for o_data in acct_data.get("orders", []):
                        order = PaperOrder(
                            order_id=o_data["order_id"],
                            symbol=o_data["symbol"],
                            action=o_data["action"],
                            quantity=o_data["quantity"],
                            price=o_data["price"],
                            timestamp=datetime.fromisoformat(o_data["timestamp"]),
                            filled=o_data.get("filled", True),
                            reason=o_data.get("reason", ""),
                            commission=o_data.get("commission", 0.0),
                        )
                        acct.orders.append(order)
                    self._accounts[acct_id] = acct
                    if acct_id == "default":
                        self._default_account = acct
                logger.info("纸上账户已从磁盘恢复: {} 个账户", len(self._accounts))
        except Exception as e:
            logger.warning("纸上账户磁盘恢复失败: {}", e)

    def _save_to_disk(self) -> None:
        try:
            os.makedirs(self._PERSIST_PATH.parent, exist_ok=True)
            data = {"accounts": {}}
            for acct_id, acct in self._accounts.items():
                data["accounts"][acct_id] = {
                    "initial_capital": acct.initial_capital,
                    "capital": acct.capital,
                    "positions": {
                        sym: {
                            "symbol": p.symbol, "quantity": p.quantity,
                            "avg_cost": p.avg_cost,
                            "entry_time": p.entry_time.isoformat() if p.entry_time else None,
                            "total_commission": p.total_commission,
                        }
                        for sym, p in acct.positions.items()
                    },
                    "orders": [
                        {
                            "order_id": o.order_id, "symbol": o.symbol,
                            "action": o.action, "quantity": o.quantity,
                            "price": o.price, "timestamp": o.timestamp.isoformat(),
                            "filled": o.filled, "reason": o.reason,
                            "commission": o.commission,
                        }
                        for o in acct.orders[-200:]
                    ],
                }
            tmp_path = self._PERSIST_PATH.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            tmp_path.rename(self._PERSIST_PATH)
        except Exception as e:
            logger.warning("纸上账户磁盘保存失败: {}", e)

    def get_or_create_account(self, account_id: str = "default",
                               initial_capital: float = 100_000) -> PaperAccount:
        if account_id not in self._accounts:
            self._accounts[account_id] = PaperAccount(
                account_id=account_id, initial_capital=initial_capital,
                capital=initial_capital,
            )
            logger.info("纸上账户创建: {} 本金={:.0f}", account_id, initial_capital)
            if account_id == "default":
                self._default_account = self._accounts[account_id]
            self._save_to_disk()
        return self._accounts[account_id]

    async def execute_signal(self, symbol: str, decision: str, price: float,
                              confidence: float = 0.5, account_id: str = "default",
                              reason: str = "") -> Optional[PaperOrder]:
        """根据AI决策执行纸上交易"""
        account = self.get_or_create_account(account_id)

        if decision in ("HOLD", "WAIT"):
            # Record as journal entry (no trade, visible in history)
            account.orders.append(PaperOrder(
                order_id=f"paper_{symbol}_{int(datetime.now(timezone.utc).timestamp())}",
                symbol=symbol, action=decision, quantity=0, price=price,
                timestamp=datetime.now(timezone.utc), filled=True,
                reason=f"{'持仓观望' if decision=='HOLD' else '等待'} | {reason}",
                commission=0.0,
            ))
            self._save_to_disk()
            return None

        if decision == "BUY":
            if confidence is None or confidence <= 0:
                logger.info("纸上交易: {} BUY跳过 无置信度数据", symbol)
                return None
            allocation = confidence * 0.20 * account.capital
            # 高价股(单价>capital/100)允许单股买入, 普通股按100股一手
            if price > account.capital / 100:
                quantity = max(1, int(allocation / price))
            else:
                lot = 100
                quantity = int(allocation / price / lot) * lot
            if quantity > 0:
                result = account.execute_buy(symbol, price, quantity, reason=reason)
                self._save_to_disk()
                return result
            logger.info("纸上交易: {} BUY跳过 资金不足 (分配={:.0f} 价格={:.2f})", symbol, allocation, price)

        elif decision == "SELL":
            result = account.execute_sell(symbol, price, reason=reason)
            self._save_to_disk()
            return result

        return None

    async def mark_to_market(self, prices: dict[str, float]):
        """按市价估值所有持仓（用于P&L快照）；无报价持仓跳过估值，不静默记为 0 盈亏"""
        for account in self._accounts.values():
            equity = account.capital
            for sym, pos in account.positions.items():
                current_price = prices.get(sym)
                if current_price is None or current_price <= 0:
                    continue  # 无报价(如停牌)持仓不参与估值
                equity += pos.market_value(current_price)
            account.equity_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "equity": round(equity, 2),
                "pnl_pct": round((equity - account.initial_capital) / account.initial_capital * 100, 2),
            })
            if len(account.equity_history) > 500:
                account.equity_history = account.equity_history[-500:]

    async def get_summary(self, account_id: str = "default") -> dict:
        account = self._accounts.get(account_id)
        if not account:
            return {"error": f"账户 {account_id} 不存在"}
        return account.get_summary()


# 全局单例
_paper_manager: Optional[PaperTradeManager] = None


def get_paper_manager(bus=None) -> PaperTradeManager:
    global _paper_manager
    if _paper_manager is None:
        if bus is None:
            raise ValueError("首次获取需要传入 bus 参数")
        _paper_manager = PaperTradeManager(bus)
    return _paper_manager

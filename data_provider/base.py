"""
Market Trace V6.0 — 数据源抽象基类
适配器模式：所有数据源实现必须继承此基类
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from core.schema import MarketData, Level2Snapshot
from core.bus import MessageBus


class DataProviderBase(ABC):
    """
    数据源适配器基类

    所有数据源（AkShare / XTick / Yquoter / Tushare）必须实现此接口。
    严禁修改此接口的方法签名，确保向后兼容。
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any], source_name: str):
        self.bus = bus
        self.config = config
        self.source_name = source_name
        self._running = True

    @abstractmethod
    async def fetch_kline(
        self, symbol: str, start: str, end: str, period: str = "daily"
    ) -> list[MarketData]:
        """
        获取 K 线数据

        Args:
            symbol: 股票代码 (如 "000001" 或 "sh000001")
            start: 起始日期 "YYYYMMDD"
            end: 结束日期 "YYYYMMDD"
            period: 周期 ("daily" / "weekly" / "monthly")

        Returns:
            标准化 MarketData 列表
        """
        ...

    @abstractmethod
    async def fetch_realtime(self, symbol: str) -> Optional[dict[str, Any]]:
        """
        获取实时行情

        Returns:
            {price, change_pct, volume, amount, ...} 或 None
        """
        ...

    @abstractmethod
    async def fetch_fund_flow(self, symbol: str) -> Optional[dict[str, Any]]:
        """
        获取个股资金流向（主力/超大单/大单/中单/小单）

        Returns:
            {main_net_inflow, super_large_net, large_net, ...} 或 None
        """
        ...

    @abstractmethod
    async def fetch_macro_indices(self) -> Optional[dict[str, Any]]:
        """
        获取宏观指标（指数行情、市场PE、板块轮动等）

        Returns:
            {sh_index, sz_index, market_pe, sectors, ...} 或 None
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """数据源健康检查"""
        ...

    async def cache_and_publish(
        self,
        data: list[MarketData],
        symbol: str,
        event_type: str = "DATA_UPDATED",
    ) -> None:
        """
        标准化数据存入 Redis 缓存 + 发布事件

        该方法是所有数据源的统一出口：
        1. 数据写入 Redis 缓存（key: market:raw:{symbol}）
        2. 发布事件通知所有订阅 Agent
        """
        cache_key = f"market:raw:{symbol}"
        payload = [
            {
                "symbol": d.symbol,
                "timestamp": d.timestamp.isoformat(),
                "open": d.open,
                "high": d.high,
                "low": d.low,
                "close": d.close,
                "volume": d.volume,
                "amount": d.amount,
                "source": d.source,
            }
            for d in data
        ]

        ttl = self.config.get("anti_scraping", {}).get("max_cache_age_seconds", 300)
        await self.bus.cache_set(cache_key, payload, ttl=ttl)

        await self.bus.publish("events:data", {
            "event": event_type,
            "symbol": symbol,
            "source": self.source_name,
            "timestamp": datetime.now().isoformat(),
            "records": len(data),
        })

    async def cache_and_publish_dict(
        self,
        data: dict[str, Any],
        cache_key: str,
        channel: str = "events:data",
        event_type: str = "DATA_UPDATED",
    ) -> None:
        """非 K 线数据的缓存与发布（资金流向、宏观等）"""
        ttl = self.config.get("anti_scraping", {}).get("max_cache_age_seconds", 300)
        await self.bus.cache_set(cache_key, data, ttl=ttl)

        await self.bus.publish(channel, {
            "event": event_type,
            "cache_key": cache_key,
            "source": self.source_name,
            "timestamp": datetime.now().isoformat(),
        })

    def stop(self) -> None:
        """停止数据源（优雅关闭）"""
        self._running = False

    @staticmethod
    def _normalize_symbol(symbol: str) -> tuple[str, str]:
        """
        标准化股票代码

        Args:
            symbol: "000001" / "sh000001" / "SZ000001"

        Returns:
            (market, code): market ∈ {"sh", "sz"}, code 为 6 位数字
        """
        s = symbol.strip().lower()
        for prefix in ("sh", "sz"):
            if s.startswith(prefix):
                return prefix, s[len(prefix):].zfill(6)

        code = s.zfill(6)
        if code.startswith("6"):
            market = "sh"
        elif code.startswith(("0", "3")):
            market = "sz"
        else:
            market = "sz"
        return market, code

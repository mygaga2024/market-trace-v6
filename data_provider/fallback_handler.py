"""
Market Trace V6.0 — 数据源降级处理器
多源切换 + 缓存回退 + 数据缺失告警
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from core.bus import MessageBus
from data_provider.base import DataProviderBase


class FallbackHandler:
    """
    降级处理器

    策略链：
    1. 主数据源（AkShare）正常 → 直接返回
    2. 主数据源失败 → 尝试 Redis 缓存
    3. 缓存可用且新鲜 → 标记 degraded 返回
    4. 缓存过期 → 标记 stale 返回 + 警告日志
    5. 完全不可用 → 发布 DATA_MISSING 事件，返回 None
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]):
        self.bus = bus
        self.cache_ttl = config.get("anti_scraping", {}).get("max_cache_age_seconds", 300)
        self._data_unavailable_count: dict[str, int] = {}
        self._max_unavailable = 10

    async def try_fetch(
        self,
        primary: DataProviderBase,
        fetch_method: str,
        *args: Any,
        symbol: str = "",
        **kwargs: Any,
    ) -> Any:
        """
        执行数据获取，失败时自动降级

        Args:
            primary: 主数据源实例
            fetch_method: 数据源方法名 (如 "fetch_kline")
            symbol: 用于缓存 key 的股票代码
        """
        method = getattr(primary, fetch_method, None)
        if method is None:
            logger.error("数据源方法不存在: {}.{}", primary.source_name, fetch_method)
            return await self._cache_fallback(primary.source_name, symbol)

        try:
            result = await method(*args, **kwargs)
            if result is not None and (not isinstance(result, list) or len(result) > 0):
                self._reset_unavailable(symbol)
                return result
        except Exception as e:
            logger.warning("主数据源 [{}] {} 失败: {}", primary.source_name, fetch_method, e)

        return await self._cache_fallback(primary.source_name, symbol)

    async def _cache_fallback(self, source_name: str, symbol: str) -> Any:
        """缓存降级"""
        if not symbol:
            return None

        cache_key = f"market:raw:{symbol}"
        cached = await self.bus.cache_get(cache_key)

        if cached is None:
            logger.error("缓存完全未命中 [{}]: {}", source_name, symbol)
            await self._signal_missing(source_name, symbol)
            return None

        age = self._estimate_cache_age(cached)
        if age is not None and age < self.cache_ttl:
            logger.info("缓存命中 [{}]: {} ({}s 前)", source_name, symbol, age)
            return self._tag_cached(cached, degraded=False)
        else:
            logger.warning("缓存过期 [{}]: {} ({}s 前)", source_name, symbol, age)
            return self._tag_cached(cached, degraded=True, stale=True)

    async def _signal_missing(self, source_name: str, symbol: str) -> None:
        """发布数据缺失告警"""
        self._data_unavailable_count[symbol] = self._data_unavailable_count.get(symbol, 0) + 1
        consecutive = self._data_unavailable_count[symbol]

        severity = "critical" if consecutive >= self._max_unavailable else "warning"

        await self.bus.publish("events:data", {
            "event": "DATA_MISSING",
            "symbol": symbol,
            "source": source_name,
            "consecutive_failures": consecutive,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if severity == "critical":
            logger.critical("数据源 [{}] 长时间不可用! {} 连续失败 {} 次", source_name, symbol, consecutive)
        else:
            logger.warning("数据缺失 [{}]: {} ({}次)", source_name, symbol, consecutive)

    def _reset_unavailable(self, symbol: str) -> None:
        """重置指定标的的不可用计数"""
        self._data_unavailable_count.pop(symbol, None)

    @staticmethod
    def _estimate_cache_age(cached: Any) -> Optional[float]:
        """估算缓存年龄（秒）"""
        try:
            if isinstance(cached, list) and len(cached) > 0:
                ts = cached[-1].get("timestamp", "")
            elif isinstance(cached, dict):
                ts = cached.get("timestamp", "")
            else:
                return None

            if not ts:
                return None
            dt = datetime.fromisoformat(ts)
            # 如果时间戳无时区信息，假定为 UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            return None

    @staticmethod
    def _tag_cached(data: Any, degraded: bool = False, stale: bool = False) -> Any:
        """标记缓存数据状态"""
        tag = {"cached": True, "degraded": degraded, "stale": stale}
        if isinstance(data, list):
            return [{**item, **tag} for item in data]
        elif isinstance(data, dict):
            data.update(tag)
        return data

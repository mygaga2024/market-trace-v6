"""
Market Trace V6.0 — 股票池预加载服务
后台并发预加载 K 线到 Redis 缓存（热门并发 + 温数据队列补全）
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from core.schema import MarketData


# 共享状态
_prefetch_sem = asyncio.Semaphore(5)
_cached_symbols: set = set()
_prefetch_queue: asyncio.Queue = asyncio.Queue()
_prefetch_done = asyncio.Event()

_prefetch_tp = None
_prefetch_ap = None
_prefetch_tushare_token = ""
_prefetch_last_ts_call = 0.0

# 管理的后台 task 引用（防止 GC 回收 + 异常静默丢失）
_background_tasks: list[asyncio.Task] = []


def _build_cache_entry(klines: list) -> list[dict]:
    return [{"close": k.close, "open": k.open, "high": k.high, "low": k.low,
             "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()}
            for k in klines]


async def _ts_rate_limit() -> None:
    """Tushare 限频: 200次/分钟 ≈ 0.3s/次"""
    global _prefetch_last_ts_call
    now = time.monotonic()
    elapsed = now - _prefetch_last_ts_call
    if elapsed < 0.35:
        await asyncio.sleep(0.35 - elapsed)
    _prefetch_last_ts_call = time.monotonic()


async def _fetch_one_symbol(symbol: str, bus, config: dict) -> bool:
    """拉取并缓存单只股票K线 (Tushare优先 → AkShare备用)"""
    cache_key = f"market:raw:{symbol}"
    if symbol in _cached_symbols:
        return True

    async with _prefetch_sem:
        cached = None
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")

        if _prefetch_tushare_token:
            try:
                await _ts_rate_limit()
                klines = await _prefetch_tp.fetch_kline(symbol, start_date, end_date)
                if klines:
                    last_date = klines[-1].timestamp.date()
                    if (datetime.now().date() - last_date).days <= 2:
                        cached = _build_cache_entry(klines)
                        if bus:
                            await bus.cache_set(cache_key, cached, ttl=7200)
            except Exception as e:
                logger.debug("Tushare 预加载 {} 失败: {}", symbol, e)

        if not cached:
            try:
                klines = await _prefetch_ap.fetch_kline(symbol, start_date, end_date)
                if klines:
                    cached = _build_cache_entry(klines)
                    if bus:
                        await bus.cache_set(cache_key, cached, ttl=7200)
            except Exception as e:
                logger.debug("AkShare 预加载 {} 失败: {}", symbol, e)

        if cached:
            _cached_symbols.add(symbol)
            logger.info("预加载 {}: {} 条K线", symbol, len(cached))
            if bus:
                await bus.publish("events:data", {"event": "DATA_UPDATED", "symbol": symbol})
            return True
        else:
            logger.warning("预加载 {}: 数据拉取失败", symbol)
            return False


async def _prefetch_worker(bus, config: dict) -> None:
    """后台消费队列 (低并发, 慢慢补全剩余股票)"""
    warm_sem = asyncio.Semaphore(3)

    async def _slow_fetch(sym):
        try:
            async with warm_sem:
                await _fetch_one_symbol(sym, bus, config)
        finally:
            _prefetch_queue.task_done()

    tasks = []
    while True:
        try:
            symbol = await asyncio.wait_for(_prefetch_queue.get(), timeout=10)
        except asyncio.TimeoutError:
            break
        tasks.append(asyncio.create_task(_slow_fetch(symbol)))

    if tasks:
        await asyncio.gather(*tasks)
    _prefetch_done.set()


async def prefetch_stock_pool(bus, config: dict) -> None:
    """后台并发预加载股票池K线到Redis缓存"""
    global _prefetch_tp, _prefetch_ap, _prefetch_tushare_token

    await asyncio.sleep(3)

    stock_pool = config.get("stock_pool", [])
    provider_cfg = [p for p in config.get("data_providers", []) if p.get("enabled")]
    _prefetch_tushare_token = next(
        (p.get("token") for p in provider_cfg if p.get("name") == "tushare" and p.get("token")), "")

    from data_provider.tushare_impl import TushareProvider
    from data_provider.akshare_impl import AkShareProvider

    if _prefetch_tushare_token:
        _prefetch_tp = TushareProvider(bus, config, token=_prefetch_tushare_token)
    _prefetch_ap = AkShareProvider(bus, config)

    hot_count = min(20, len(stock_pool))
    hot_symbols = stock_pool[:hot_count]
    warm_symbols = stock_pool[hot_count:]

    logger.info("并发预加载 热门 {} 只 (并发度=5)…", len(hot_symbols))
    t0 = time.monotonic()
    results = await asyncio.gather(
        *[_fetch_one_symbol(s, bus, config) for s in hot_symbols],
        return_exceptions=True,
    )
    cached_count = sum(1 for r in results if r is True)
    logger.info("热门预加载完成: {}/{} 只 ({:.1f}s)", cached_count, len(hot_symbols), time.monotonic() - t0)

    if warm_symbols:
        for s in warm_symbols:
            await _prefetch_queue.put(s)
        logger.info("温数据 {} 只进入后台队列，逐步补全…", len(warm_symbols))
        task = asyncio.create_task(_prefetch_worker(bus, config))
        _background_tasks.append(task)


async def ensure_symbol_cached(symbol: str, bus, config: dict) -> None:
    """懒加载: 确保符号已缓存，未缓存则即时拉取"""
    global _prefetch_ap
    if symbol in _cached_symbols:
        return
    if _prefetch_ap is None:
        from data_provider.akshare_impl import AkShareProvider
        _prefetch_ap = AkShareProvider(bus, config)
    cached = await _fetch_one_symbol(symbol, bus, config)
    if not cached:
        logger.warning("懒加载 {} 失败", symbol)


def get_prefetch_providers():
    """获取预加载使用的 Provider 实例（供 analyzer 复用）"""
    return _prefetch_tp, _prefetch_ap

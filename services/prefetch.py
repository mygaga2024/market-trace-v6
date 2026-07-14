"""
Market Trace V6.0 — 股票池预加载服务
后台并发预加载 K 线到 Redis 缓存（热门并发 + 温数据队列补全）
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from loguru import logger

from core.schema import MarketData


# 共享状态（asyncio 原语在事件循环中懒初始化，避免绑定到错误的 loop）
_prefetch_sem: asyncio.Semaphore | None = None
_cached_symbols: set = set()
_prefetch_queue: asyncio.Queue | None = None
_prefetch_done: asyncio.Event | None = None

_prefetch_tp = None
_prefetch_ap = None
_prefetch_tushare_token = ""
_prefetch_last_ts_call = 0.0

# 管理的后台 task 引用（防止 GC 回收 + 异常静默丢失）
_background_tasks: list[asyncio.Task] = []


def _ensure_asyncio_primitives():
    """确保 asyncio 原语已在当前事件循环中创建"""
    global _prefetch_sem, _prefetch_queue, _prefetch_done
    if _prefetch_sem is None:
        _prefetch_sem = asyncio.Semaphore(5)
    if _prefetch_queue is None:
        _prefetch_queue = asyncio.Queue()
    if _prefetch_done is None:
        _prefetch_done = asyncio.Event()


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


async def _fetch_one_symbol(symbol: str, bus, config: dict, force: bool = False) -> bool:
    """拉取并缓存单只股票K线 (Tushare优先 → AkShare备用)"""
    cache_key = f"market:raw:{symbol}"
    if not force and symbol in _cached_symbols:
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

    _ensure_asyncio_primitives()
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

    # 启动交易时段定期刷新
    refresh_task = asyncio.create_task(_periodic_refresh_loop(bus, config, stock_pool))
    _background_tasks.append(refresh_task)


def _is_trading_time() -> bool:
    """判断当前是否在 A 股交易时段内（周一~周五 9:30-15:05 北京时间）"""
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    if now.weekday() >= 5:
        return False
    t = now.time()
    from datetime import time as ttime
    return ttime(9, 29) <= t <= ttime(15, 5)


async def _periodic_refresh_loop(bus, config: dict, stock_pool: list[str]) -> None:
    """交易时段每 5 分钟刷新一次热门股票 K 线缓存"""
    while True:
        try:
            if _is_trading_time():
                hot = stock_pool[:min(20, len(stock_pool))]
                logger.info("交易时段刷新 {} 只热门股票缓存", len(hot))
                results = await asyncio.gather(
                    *[_fetch_one_symbol(s, bus, config, force=True) for s in hot],
                    return_exceptions=True,
                )
                refreshed = sum(1 for r in results if r is True)
                logger.info("交易时段刷新完成: {}/{} 只", refreshed, len(hot))
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("定期刷新异常: {}", e)
            await asyncio.sleep(60)


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


async def prefetch_stock_names(bus, config: dict) -> dict[str, str]:
    """启动时批量获取 A 股名称并缓存到 Redis key stock:names"""
    if not bus:
        return {}
    try:
        cached = await bus.cache_get("stock:names")
        if cached and isinstance(cached, dict) and cached:
            logger.info("股票名称已从 Redis 加载: {} 只", len(cached))
            return cached
    except Exception:
        pass

    stock_pool = config.get("stock_pool", [])
    if not stock_pool:
        return {}

    try:
        import akshare as ak
        logger.info("批量获取 A 股名称 (akshare)...")
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        if df is None or df.empty:
            raise ValueError("akshare 返回空数据")
        name_map: dict[str, str] = {}
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if code and name and code in set(stock_pool):
                name_map[code] = name
    except Exception as e:
        logger.warning("akshare 批量获取股票名称失败: {}，回退到新浪逐个查询", e)
        name_map: dict[str, str] = {}
        for sym in stock_pool:
            nm = await _fetch_name_via_sina(sym)
            if nm:
                name_map[sym] = nm
            await asyncio.sleep(0.1)

    if name_map:
        try:
            await bus.cache_set("stock:names", name_map, ttl=86400)
        except Exception:
            pass
        logger.info("股票名称已缓存: {} 只", len(name_map))
    else:
        logger.warning("未获取到任何股票名称")

    return name_map


_stock_name_cache: dict[str, str] = {}  # 进程内缓存，兜底


_name_cache_sina: httpx.AsyncClient | None = None


def _get_sina_client() -> httpx.AsyncClient:
    global _name_cache_sina
    if _name_cache_sina is None or _name_cache_sina.is_closed:
        _name_cache_sina = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            headers={"Referer": "https://finance.sina.com.cn"},
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
        )
    return _name_cache_sina


async def _fetch_name_via_sina(symbol: str) -> str:
    """通过新浪行情接口获取单只股票名称"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    url = f"http://hq.sinajs.cn/list={prefix}{symbol}"
    try:
        client = _get_sina_client()
        r = await client.get(url)
        r.encoding = "gbk"
        text = r.text
        if text and '="' in text:
            name = text.split('="')[1].split(",")[0].strip()
            if name and name != symbol:
                return name
    except Exception:
        pass
    return ""


async def fetch_stock_price_via_sina(symbol: str):
    """通过新浪行情接口获取单只股票名称+实时价格+涨跌幅，返回 (name, price, change_pct)"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    url = f"http://hq.sinajs.cn/list={prefix}{symbol}"
    try:
        client = _get_sina_client()
        r = await client.get(url)
        r.encoding = "gbk"
        text = r.text
        if text and '="' in text:
            parts = text.split('="')[1].split(",")
            name = parts[0].strip() if parts[0].strip() != symbol else ""
            try:
                price = float(parts[3]) if len(parts) > 3 and parts[3] else None
            except (ValueError, IndexError):
                price = None
            try:
                prev_close = float(parts[2]) if len(parts) > 2 and parts[2] else None
            except (ValueError, IndexError):
                prev_close = None
            change_pct = None
            if price and prev_close and prev_close != 0:
                change_pct = round((price - prev_close) / prev_close * 100, 2)
            return name, price, change_pct
    except Exception:
        pass
    return "", None, None


async def fetch_stock_price_tencent(symbol: str):
    """通过腾讯行情接口获取单只股票名称+实时价格+涨跌幅，返回 (name, price, change_pct)
    与 services/analyzer.py 的 _apply_tencent_quote 使用同一数据源"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    url = f"http://qt.gtimg.cn/q={prefix}{symbol}"
    try:
        from services.analyzer import _get_tencent_client
        client = _get_tencent_client()
        r = await client.get(url)
        r.encoding = "gbk"
        text = r.text
        if "~" not in text:
            return "", None, None
        fields = text.split("~")
        if len(fields) < 5:
            return "", None, None
        name = fields[1].strip() if len(fields) > 1 else ""
        try:
            price = float(fields[3]) if fields[3] else None
        except (ValueError, IndexError):
            price = None
        try:
            prev_close = float(fields[4]) if fields[4] else None
        except (ValueError, IndexError):
            prev_close = None
        change_pct = None
        if price and prev_close and prev_close != 0:
            change_pct = round((price - prev_close) / prev_close * 100, 2)
        return name, price, change_pct
    except Exception:
        pass
    return "", None, None


async def get_stock_name(symbol: str, bus) -> str:
    """获取股票名称（Redis → 进程缓存 → 新浪实时查询）"""
    if symbol in _stock_name_cache:
        return _stock_name_cache[symbol]

    if bus:
        try:
            names = await bus.cache_get("stock:names")
            if isinstance(names, dict) and symbol in names:
                _stock_name_cache[symbol] = names[symbol]
                return names[symbol]
        except Exception:
            pass

    name = await _fetch_name_via_sina(symbol)
    if name:
        _stock_name_cache[symbol] = name
        return name

    return ""

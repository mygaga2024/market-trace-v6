"""
Market Trace V6.0 — 全市场扫描器
5000+ A股批量扫描、策略筛选、结果排行
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
from loguru import logger

from core.strategies import STRATEGIES

# 全市场股票列表缓存（进程内 + Redis）
_stock_list_cache: list[dict] | None = None
_stock_list_ts: float = 0.0


async def get_all_stocks(bus) -> list[dict]:
    """获取全市场股票列表（缓存1小时）"""
    global _stock_list_cache, _stock_list_ts
    now = time.monotonic()

    # 进程内缓存
    if _stock_list_cache and (now - _stock_list_ts) < 3600:
        return _stock_list_cache

    # Redis 缓存
    if bus:
        try:
            cached = await bus.cache_get("market:stock_list")
            if cached and isinstance(cached, list) and len(cached) > 1000:
                _stock_list_cache = cached
                _stock_list_ts = now
                logger.info("股票列表从 Redis 加载: {} 只", len(cached))
                return cached
        except Exception:
            pass

    # 从 akshare 拉取（优先用带价格的 spot，失败则用简版）
    stocks: list[dict] = []
    has_prices = False

    try:
        import akshare as ak
        logger.info("拉取全市场股票列表(带实时价格)...")
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue
                try:
                    price = float(row.get("最新价", 0) or 0)
                except (ValueError, TypeError):
                    price = 0.0
                try:
                    change_pct = float(row.get("涨跌幅", 0) or 0)
                except (ValueError, TypeError):
                    change_pct = 0.0
                try:
                    vol = float(row.get("成交量", 0) or 0)
                except (ValueError, TypeError):
                    vol = 0.0
                stocks.append({"symbol": code, "name": name, "price": price, "change_pct": change_pct, "volume": vol})
            has_prices = any(s["price"] > 0 for s in stocks[:100])
            logger.info("股票列表: {} 只 (有价格={})", len(stocks), has_prices)
    except Exception as e:
        logger.warning("akshare spot 失败: {}", e)

    # 降级：仅代码名称（无价格）
    if not stocks:
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_info_a_code_name)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("code", row.get("A股代码", ""))).strip()
                    name = str(row.get("name", row.get("A股简称", ""))).strip()
                    if code and name:
                        stocks.append({"symbol": code, "name": name, "price": 0, "change_pct": 0, "volume": 0})
                logger.info("简版股票列表: {} 只(无实时价格)", len(stocks))
        except Exception as e:
            logger.error("简版也失败: {}", e)

    # 如果无价格数据，用 Sina 批量补全
    if stocks and not has_prices:
        await _enrich_prices_via_sina(stocks)
        has_prices = True

    if stocks and has_prices:
        _stock_list_cache = stocks
        _stock_list_ts = now
        if bus:
            await bus.cache_set("market:stock_list", stocks, ttl=7200)
        logger.info("股票列表已缓存: {} 只", len(stocks))

    return stocks


async def _enrich_prices_via_sina(stocks: list[dict]) -> None:
    """用 Sina 批量接口补全实时价格（每批50只）"""
    import requests as _requests
    batch_size = 50
    sem = asyncio.Semaphore(5)

    async def _fetch_batch(batch: list[dict]) -> None:
        async with sem:
            codes = []
            for s in batch:
                prefix = "sh" if s["symbol"].startswith(("6", "9")) else "sz"
                codes.append(f"{prefix}{s['symbol']}")
            url = f"http://hq.sinajs.cn/list={','.join(codes)}"
            try:
                r = await asyncio.to_thread(
                    _requests.get, url,
                    headers={"Referer": "https://finance.sina.com.cn"},
                    timeout=10,
                )
                r.encoding = "gbk"
                lines = [l for l in r.text.strip().split("\n") if '="' in l]
                for line in lines:
                    try:
                        code_part = line.split("=")[0].replace("var hq_str_", "").strip()
                        data = line.split('="')[1].rstrip('";')
                        parts = data.split(",")
                        if len(parts) < 4:
                            continue
                        symbol = code_part[2:]  # remove sh/sz prefix
                        price = float(parts[3]) if parts[3] else 0.0
                        prev_close = float(parts[2]) if parts[2] else 0.0
                        chg = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
                        for s in batch:
                            if s["symbol"] == symbol:
                                s["price"] = price
                                s["change_pct"] = chg
                                break
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("Sina批量价格失败: {}", e)

    batches = [stocks[i:i + batch_size] for i in range(0, len(stocks), batch_size)]
    tasks = [asyncio.create_task(_fetch_batch(b)) for b in batches]
    await asyncio.gather(*tasks, return_exceptions=True)
    priced = sum(1 for s in stocks if s["price"] > 0)
    logger.info("Sina补全价格: {}/{} 只", priced, len(stocks))


async def quick_scan(strategy: str, limit: int = 50,
                     min_price: float = 1.0, max_price: float = 9999,
                     bus=None) -> dict:
    """
    快速全市场扫描（两阶段）
    阶段1: 用实时行情数据粗筛 (price/chg/vol)
    阶段2: 对粗筛通过的股票做深度策略检查 (需缓存K线)
    """
    info = STRATEGIES.get(strategy)
    if not info:
        return {"error": f"策略不存在: {strategy}", "strategy": strategy}
    label = info["label"]
    check_fn = info["check"]

    t0 = time.monotonic()
    stocks = await get_all_stocks(bus)
    if not stocks:
        return {"error": "无法获取股票列表", "strategy": strategy}

    logger.info("全市场扫描开始: {} ({} 只)", label, len(stocks))

    # 阶段1: 实时行情粗筛（无需缓存K线）
    rough_hits: list[dict] = []
    for s in stocks:
        price = s.get("price", 0)
        chg = s.get("change_pct", 0)
        if min_price <= price <= max_price and price > 0:
            # 简单初筛（不同策略用不同条件）
            if strategy == "breakout" and chg > 1 and price > 5:
                rough_hits.append(s)
            elif strategy == "oversold" and chg < -3:
                rough_hits.append(s)
            elif strategy == "strength" and chg > 2:
                rough_hits.append(s)
            elif strategy == "risk" and chg < -5:
                rough_hits.append(s)
            elif strategy == "ma_golden_cross" and chg > 0.5:
                rough_hits.append(s)
            elif strategy == "volume_breakout" and chg > 3:
                rough_hits.append(s)
            elif strategy == "rsi_reversal" and chg < -2:
                rough_hits.append(s)

    logger.info("阶段1粗筛: {} → {} 只", len(stocks), len(rough_hits))

    # 阶段2: 深度策略检查（仅对粗筛通过的股票）
    sem = asyncio.Semaphore(10)
    hits: list[dict] = []
    checked = 0
    too_few_data = 0

    async def _deep_check(stock: dict) -> None:
        nonlocal checked, too_few_data
        async with sem:
            checked += 1
            try:
                cached = await bus.cache_get(f"market:raw:{stock['symbol']}") if bus else None
                if not cached or len(cached) < 20:
                    too_few_data += 1
                    # 无缓存时用行情数据直接输出（不验证策略）
                    hits.append({
                        "symbol": stock["symbol"],
                        "name": stock["name"],
                        "price": round(stock.get("price", 0), 2),
                        "change_pct": round(stock.get("change_pct", 0), 2),
                        "vol_ratio": 1.0,
                    })
                    return

                closes = np.array([float(r["close"]) for r in cached])
                highs = np.array([float(r["high"]) for r in cached])
                volumes = np.array([float(r["volume"]) for r in cached])

                kwargs = info.get("params", {}).copy()
                if check_fn(closes, highs, volumes, **kwargs):
                    vol_r = round(float(volumes[-1] / np.mean(volumes[:-1])), 2) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0
                    hits.append({
                        "symbol": stock["symbol"],
                        "name": stock["name"],
                        "price": round(float(closes[-1]), 2),
                        "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else round(stock.get("change_pct", 0), 2),
                        "vol_ratio": vol_r,
                    })
                    logger.debug("命中: {} {}", stock["symbol"], stock["name"])
            except Exception as e:
                logger.debug("扫描 {} 失败: {}", stock["symbol"], e)

    if rough_hits:
        tasks = [asyncio.create_task(_deep_check(s)) for s in rough_hits]
        await asyncio.gather(*tasks, return_exceptions=True)

    hits.sort(key=lambda x: (-x["vol_ratio"], -abs(x["change_pct"])))
    elapsed = time.monotonic() - t0
    logger.info("全市场扫描完成: {:.1f}s, 命中 {}/{}({})", elapsed, len(hits), checked, too_few_data)

    return {
        "strategy": label, "strategy_id": strategy,
        "total_stocks": len(stocks), "rough_filtered": len(rough_hits),
        "deep_checked": checked, "too_few_data": too_few_data,
        "matched": len(hits), "elapsed_seconds": round(elapsed, 1),
        "results": hits[:limit],
    }


async def smart_scan(bus, config: dict, limit: int = 30) -> dict:
    """
    智能扫描：对有缓存K线的股票做7策略深度评分。
    全市场粗筛 + 缓存股票深度分析。
    """
    stocks = await get_all_stocks(bus)
    if not stocks:
        return {"error": "无法获取股票列表"}

    t0 = time.monotonic()
    sem = asyncio.Semaphore(10)
    scored: list[dict] = []
    skipped = 0
    checked = 0

    async def _score_one(stock: dict) -> None:
        nonlocal skipped, checked
        async with sem:
            try:
                cached = await bus.cache_get(f"market:raw:{stock['symbol']}") if bus else None
                if not cached or len(cached) < 30:
                    skipped += 1
                    return
                checked += 1

                closes = np.array([float(r["close"]) for r in cached])
                highs = np.array([float(r["high"]) for r in cached])
                volumes = np.array([float(r["volume"]) for r in cached])

                best_strategy = ""
                best_label = ""
                best_score = -999
                for name, info in STRATEGIES.items():
                    try:
                        kwargs = info.get("params", {}).copy()
                        if info["check"](closes, highs, volumes, **kwargs):
                            chg = abs((closes[-1] - closes[-2]) / closes[-2]) if len(closes) > 1 else 0
                            vol_r = float(volumes[-1] / np.mean(volumes[:-1])) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0
                            score = vol_r + chg * 10 + (abs(stock.get("change_pct", 0)) * 0.5)
                            if score > best_score:
                                best_score = score
                                best_strategy = name
                                best_label = info["label"]
                    except Exception:
                        pass

                if best_strategy:
                    scored.append({
                        "symbol": stock["symbol"],
                        "name": stock["name"],
                        "price": round(float(closes[-1]), 2),
                        "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else round(stock.get("change_pct", 0), 2),
                        "strategy": best_strategy,
                        "strategy_label": best_label,
                        "score": round(best_score, 2),
                    })
            except Exception:
                pass

    # 同时扫描全部（主要命中缓存的stock_pool股票）
    tasks = [asyncio.create_task(_score_one(s)) for s in stocks]
    await asyncio.gather(*tasks, return_exceptions=True)

    scored.sort(key=lambda x: -x["score"])
    elapsed = time.monotonic() - t0

    return {
        "total": len(stocks), "checked": checked, "scored": len(scored), "skipped": skipped,
        "elapsed_seconds": round(elapsed, 1),
        "results": scored[:limit],
    }

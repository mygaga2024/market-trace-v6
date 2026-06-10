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

    # 从 akshare 拉取
    try:
        import akshare as ak
        logger.info("拉取全市场股票列表...")
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        if df is not None and not df.empty:
            stocks = []
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
                stocks.append({
                    "symbol": code, "name": name, "price": price,
                    "change_pct": change_pct, "volume": vol,
                })
            if stocks:
                _stock_list_cache = stocks
                _stock_list_ts = now
                if bus:
                    await bus.cache_set("market:stock_list", stocks, ttl=7200)
                logger.info("股票列表已缓存: {} 只", len(stocks))
                return stocks
    except Exception as e:
        logger.warning("akshare 全市场拉取失败: {}，尝试简版", e)

    # 降级：只拉代码名称
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_info_a_code_name)
        if df is not None and not df.empty:
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("code", row.get("A股代码", ""))).strip()
                name = str(row.get("name", row.get("A股简称", ""))).strip()
                if code and name:
                    stocks.append({"symbol": code, "name": name, "price": 0, "change_pct": 0, "volume": 0})
            if stocks:
                _stock_list_cache = stocks
                _stock_list_ts = now
                logger.info("简版股票列表: {} 只(无实时价格)", len(stocks))
                return stocks
    except Exception as e:
        logger.error("简版股票列表也失败: {}", e)

    return []


async def quick_scan(strategy: str, limit: int = 50,
                     min_price: float = 1.0, max_price: float = 9999,
                     bus=None) -> dict:
    """
    快速全市场扫描
    1. 拉取全市场股票列表（带实时价格）
    2. 对每只股票检查策略条件
    3. 按综合评分排序返回 top N
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

    # 过滤价格区间
    candidates = [s for s in stocks if min_price <= s.get("price", 0) <= max_price]
    logger.info("价格过滤后: {} 只", len(candidates))

    sem = asyncio.Semaphore(10)
    hits: list[dict] = []
    too_few_data = 0
    errors = 0
    checked = 0

    async def _check_one(stock: dict) -> None:
        nonlocal too_few_data, errors, checked
        async with sem:
            try:
                cached = await bus.cache_get(f"market:raw:{stock['symbol']}") if bus else None
                if not cached or len(cached) < 20:
                    too_few_data += 1
                    return

                closes = np.array([float(r["close"]) for r in cached])
                highs = np.array([float(r["high"]) for r in cached])
                volumes = np.array([float(r["volume"]) for r in cached])

                kwargs = info.get("params", {}).copy()
                if check_fn(closes, highs, volumes, **kwargs):
                    hits.append({
                        "symbol": stock["symbol"],
                        "name": stock["name"],
                        "price": round(float(closes[-1]), 2),
                        "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else 0,
                        "vol_ratio": round(float(volumes[-1] / np.mean(volumes[:-1])), 2) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0,
                    })
                    logger.debug("命中: {} {}", stock["symbol"], stock["name"])
            except Exception as e:
                errors += 1
                logger.debug("扫描 {} 失败: {}", stock["symbol"], e)

    tasks = [asyncio.create_task(_check_one(s)) for s in candidates]
    await asyncio.gather(*tasks, return_exceptions=True)
    checked = len(candidates) - errors

    # 排序
    hits.sort(key=lambda x: (-x["vol_ratio"], -abs(x["change_pct"])))

    elapsed = time.monotonic() - t0
    logger.info("全市场扫描完成: {:.1f}s, 命中 {}/{}", elapsed, len(hits), checked)

    return {
        "strategy": label, "strategy_id": strategy,
        "total_stocks": len(stocks), "checked": checked,
        "too_few_data": too_few_data, "errors": errors,
        "matched": len(hits), "elapsed_seconds": round(elapsed, 1),
        "results": hits[:limit],
    }


async def smart_scan(bus, config: dict, limit: int = 30) -> dict:
    """
    智能扫描：对全市场跑所有7个策略，返回综合得分最高的股票。
    每只股票取其最优策略评分，按分数降序排列。
    """
    stocks = await get_all_stocks(bus)
    if not stocks:
        return {"error": "无法获取股票列表"}

    t0 = time.monotonic()
    sem = asyncio.Semaphore(10)
    scored: list[dict] = []
    skipped = 0

    async def _score_one(stock: dict) -> None:
        nonlocal skipped
        async with sem:
            try:
                cached = await bus.cache_get(f"market:raw:{stock['symbol']}") if bus else None
                if not cached or len(cached) < 30:
                    skipped += 1
                    return

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
                            # 简单评分：量比 + 涨跌幅度
                            vol_r = float(volumes[-1] / np.mean(volumes[:-1])) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0
                            chg = abs((closes[-1] - closes[-2]) / closes[-2]) if len(closes) > 1 else 0
                            score = vol_r + chg * 10
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
                        "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) > 1 else 0,
                        "strategy": best_strategy,
                        "strategy_label": best_label,
                        "score": round(best_score, 2),
                    })
            except Exception:
                pass

    tasks = [asyncio.create_task(_score_one(s)) for s in stocks]
    await asyncio.gather(*tasks, return_exceptions=True)

    scored.sort(key=lambda x: -x["score"])
    elapsed = time.monotonic() - t0

    return {
        "total": len(stocks), "scored": len(scored), "skipped": skipped,
        "elapsed_seconds": round(elapsed, 1),
        "results": scored[:limit],
    }

"""
Market Trace V6.0 — AkShare 数据源实现
异步封装 + 反爬策略 + 熔断集成 + 标准化输出 + 代理重试
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Any, Optional

import httpx
import numpy as np
from loguru import logger

from core.bus import MessageBus
from core.circuit_breaker import CircuitBreaker
from core.schema import MarketData
from data_provider.base import DataProviderBase


def _configure_proxy_requests():
    """配置 requests 库的代理超时与重试（AkShare 依赖 requests）"""
    try:
        import os
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if not proxy_url:
            return

        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=20,
            pool_block=False,
        )

        _original_get = requests.get
        _original_request = requests.Session.request

        def _patched_get(url, **kwargs):
            kwargs.setdefault("timeout", 25)
            kwargs.setdefault("verify", False)
            return _original_get(url, **kwargs)

        def _patched_session_request(self, method, url, **kwargs):
            kwargs.setdefault("timeout", 25)
            kwargs.setdefault("verify", False)
            self.mount("https://", adapter)
            self.mount("http://", adapter)
            return _original_request(self, method, url, **kwargs)

        requests.get = _patched_get
        for cls in (requests.Session,):
            if not hasattr(cls, "_mt6_patched"):
                cls.request = _patched_session_request
                cls._mt6_patched = True

        import urllib3
        urllib3.disable_warnings()
        logger.info("requests 代理重试已配置 (timeout=25s, retries=3)")
    except Exception as e:
        logger.warning("requests 代理配置失败: {}", e)


class AkShareProvider(DataProviderBase):
    """AkShare 异步数据源适配器"""

    def __init__(self, bus: MessageBus, config: dict[str, Any]):
        super().__init__(bus, config, source_name="akshare")

        _configure_proxy_requests()

        ac = config.get("anti_scraping", {})
        self._user_agents: list[str] = ac.get("user_agents", ["Mozilla/5.0"])
        self._delay_mean: float = ac.get("delay", {}).get("mean", 2.0)
        self._delay_std: float = ac.get("delay", {}).get("std", 0.5)
        self._delay_min: float = ac.get("delay", {}).get("min", 0.5)

        self._http_client: Optional[httpx.AsyncClient] = None

        cb_cfg = config.get("circuit_breaker", {})
        self._cb = CircuitBreaker(
            name="akshare",
            failure_threshold=cb_cfg.get("failure_threshold", 3),
            recovery_timeout=cb_cfg.get("recovery_timeout", 60),
            half_open_max_requests=cb_cfg.get("half_open_max_requests", 2),
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._http_client

    async def _random_delay(self) -> None:
        """高斯分布随机延迟，避免被反爬"""
        delay = max(self._delay_min, np.random.default_rng().normal(self._delay_mean, self._delay_std))
        await asyncio.sleep(delay)

    def _rotate_ua(self) -> str:
        return random.choice(self._user_agents)

    async def health_check(self) -> bool:
        try:
            import akshare as ak
            await self._random_delay()
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            return df is not None and not df.empty
        except Exception as e:
            logger.warning("AkShare 健康检查失败: {}", e)
            return False

    async def fetch_kline(
        self, symbol: str, start: str, end: str, period: str = "daily"
    ) -> list[MarketData]:
        return await self._cb.call(
            self._do_fetch_kline, symbol, start, end, period,
            fallback=self._fallback_fetch_kline,
        )

    async def _do_fetch_kline(
        self, symbol: str, start: str, end: str, period: str = "daily"
    ) -> list[MarketData]:
        import akshare as ak

        market, code = self._normalize_symbol(symbol)
        await self._random_delay()

        logger.info("AkShare 抓取 K 线: {} ({}), {} → {}", symbol, period, start, end)
        df = await asyncio.to_thread(
            ak.stock_zh_a_hist,
            symbol=code,
            period=period,
            start_date=start,
            end_date=end,
            adjust="qfq",
        )

        if df is None or df.empty:
            logger.warning("AkShare K 线返回空数据: {}", symbol)
            return []

        records = self._standardize_kline(df, symbol)

        await self.cache_and_publish(records, symbol)
        logger.info("AkShare K 线抓取完成: {} ({} 条)", symbol, len(records))
        return records

    async def _fallback_fetch_kline(
        self, symbol: str, start: str, end: str, period: str = "daily"
    ) -> list[MarketData]:
        """降级：从 Redis 缓存读取"""
        logger.warning("AkShare K 线降级: 尝试从缓存读取 {}", symbol)
        cached = await self.bus.cache_get(f"market:raw:{symbol}")
        if cached:
            records = [
                MarketData(
                    symbol=r["symbol"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    amount=r.get("amount"),
                    source="cache:akshare",
                )
                for r in cached
            ]
            logger.info("缓存命中: {} ({} 条)", symbol, len(records))
            return records
        logger.error("缓存未命中: {}，数据不可用", symbol)
        return []

    def _standardize_kline(self, df, symbol: str) -> list[MarketData]:
        """标准化 DataFrame → list[MarketData]"""
        records: list[MarketData] = []
        for _, row in df.iterrows():
            try:
                records.append(MarketData(
                    symbol=symbol,
                    timestamp=pd_timestamp(row.get("日期")),
                    open=float(row.get("开盘", 0)),
                    high=float(row.get("最高", 0)),
                    low=float(row.get("最低", 0)),
                    close=float(row.get("收盘", 0)),
                    volume=float(row.get("成交量", 0)),
                    amount=float(row.get("成交额", 0)) if row.get("成交额") else None,
                    source="akshare",
                ))
            except (ValueError, TypeError) as e:
                logger.debug("K 线行解析异常: {} → {}", row.to_dict(), e)
                continue
        return records

    async def fetch_realtime(self, symbol: str) -> Optional[dict[str, Any]]:
        return await self._cb.call(
            self._do_fetch_realtime, symbol,
            fallback=self._fallback_dict,
        )

    async def _do_fetch_realtime(self, symbol: str) -> Optional[dict[str, Any]]:
        import akshare as ak

        market, code = self._normalize_symbol(symbol)
        await self._random_delay()

        logger.debug("AkShare 抓取实时行情: {}", symbol)
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)

        if df is None or df.empty:
            return None

        row = df[df["代码"] == code]
        if row.empty:
            return None

        r = row.iloc[0]
        data = {
            "symbol": symbol,
            "name": str(r.get("名称", "")),
            "price": float(r.get("最新价", 0)),
            "change_pct": float(r.get("涨跌幅", 0)),
            "change": float(r.get("涨跌额", 0)),
            "volume": float(r.get("成交量", 0)),
            "amount": float(r.get("成交额", 0)),
            "high": float(r.get("最高", 0)),
            "low": float(r.get("最低", 0)),
            "open": float(r.get("今开", 0)),
            "pre_close": float(r.get("昨收", 0)),
            "turnover_rate": float(r.get("换手率", 0)),
            "source": "akshare",
            "timestamp": datetime.now().isoformat(),
        }

        await self.cache_and_publish_dict(data, f"market:realtime:{symbol}")
        return data

    async def fetch_fund_flow(self, symbol: str) -> Optional[dict[str, Any]]:
        return await self._cb.call(
            self._do_fetch_fund_flow, symbol,
            fallback=self._fallback_dict,
        )

    async def _do_fetch_fund_flow(self, symbol: str) -> Optional[dict[str, Any]]:
        import akshare as ak

        market, code = self._normalize_symbol(symbol)
        await self._random_delay()

        logger.debug("AkShare 抓取资金流向: {}", symbol)
        df = await asyncio.to_thread(
            ak.stock_individual_fund_flow, stock=code, market=market
        )

        if df is None or df.empty:
            return None

        latest = df.iloc[-1]
        data = {
            "symbol": symbol,
            "date": str(latest.get("日期", "")),
            "main_net_inflow": _safe_float(latest, "主力净流入-净额"),
            "main_net_inflow_pct": _safe_float(latest, "主力净流入-净占比"),
            "super_large_net": _safe_float(latest, "超大单净流入-净额"),
            "super_large_pct": _safe_float(latest, "超大单净流入-净占比"),
            "large_net": _safe_float(latest, "大单净流入-净额"),
            "large_pct": _safe_float(latest, "大单净流入-净占比"),
            "medium_net": _safe_float(latest, "中单净流入-净额"),
            "medium_pct": _safe_float(latest, "中单净流入-净占比"),
            "small_net": _safe_float(latest, "小单净流入-净额"),
            "small_pct": _safe_float(latest, "小单净流入-净占比"),
            "source": "akshare",
            "timestamp": datetime.now().isoformat(),
        }

        await self.cache_and_publish_dict(data, f"market:fundflow:{symbol}")
        return data

    async def fetch_macro_indices(self) -> Optional[dict[str, Any]]:
        return await self._cb.call(
            self._do_fetch_macro_indices,
            fallback=self._fallback_dict,
        )

    async def _do_fetch_macro_indices(self) -> Optional[dict[str, Any]]:
        import akshare as ak

        await self._random_delay()
        logger.debug("AkShare 抓取宏观指标")

        results: dict[str, Any] = {"timestamp": datetime.now().isoformat(), "source": "akshare"}

        try:
            spot_df = await asyncio.to_thread(ak.stock_zh_index_spot_em)
            if spot_df is not None and not spot_df.empty:
                results["indices"] = spot_df.head(20).to_dict(orient="records")
        except Exception as e:
            logger.warning("宏观指数抓取失败: {}", e)
            results["indices"] = []

        try:
            sector_df = await asyncio.to_thread(ak.stock_board_concept_name_em)
            if sector_df is not None and not sector_df.empty:
                results["sectors"] = sector_df.head(30).to_dict(orient="records")
        except Exception as e:
            logger.warning("板块数据抓取失败: {}", e)
            results["sectors"] = []

        await self.cache_and_publish_dict(results, "market:macro")
        return results

    async def _fallback_dict(self, *args: Any, **kwargs: Any) -> Optional[dict[str, Any]]:
        """通用降级：读取相关缓存"""
        logger.warning("AkShare 数据请求降级")
        cache_key = kwargs.get("cache_key", "market:realtime")
        cached = await self.bus.cache_get(cache_key)
        if cached:
            cached["source"] = "cache:akshare"
            cached["degraded"] = True
            return cached
        return None

    async def _do_fetch_level2(self, symbol: str) -> Optional[dict[str, Any]]:
        """
        Level-2 近似数据（AkShare 无真实 Level-2，用资金流向 + 分时替代）

        真正的 Level-2 逐笔委托需对接 XTick/Yquoter 接口，
        本方法作为过渡方案，为 Trace Agent 提供可用的近似数据。
        """
        import akshare as ak

        market, code = self._normalize_symbol(symbol)
        await self._random_delay()
        logger.debug("AkShare Level-2 近似抓取: {}", symbol)

        results: dict[str, Any] = {
            "symbol": symbol,
            "source": "akshare:approximate",
            "timestamp": datetime.now().isoformat(),
            "note": "近似 Level-2，非真实逐笔委托",
        }

        try:
            fund_flow = await self.fetch_fund_flow(symbol)
            if fund_flow:
                results["fund_flow"] = fund_flow
        except Exception:
            results["fund_flow"] = None

        try:
            realtime = await self.fetch_realtime(symbol)
            if realtime:
                results["realtime"] = realtime
        except Exception:
            results["realtime"] = None

        return results

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("AkShare 数据源已关闭")


def _safe_float(row, col: str, default: float = 0.0) -> float:
    """安全浮点数转换"""
    try:
        val = row.get(col)
        if val is None or val == "-" or val == "":
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def pd_timestamp(val) -> datetime:
    """Pandas Timestamp → datetime"""
    import pandas as pd
    if isinstance(val, pd.Timestamp):
        return val.to_pydatetime()
    if isinstance(val, str):
        return datetime.strptime(val, "%Y-%m-%d")
    return datetime.fromtimestamp(float(str(val)))

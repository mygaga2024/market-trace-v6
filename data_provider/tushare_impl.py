"""
Market Trace V6.0 — Tushare 数据源实现
Token 认证 REST API，替代被东财 WAF 拦截的实时/资金流向/板块接口
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
from loguru import logger

from core.bus import MessageBus
from core.circuit_breaker import CircuitBreaker
from core.schema import MarketData
from data_provider.base import DataProviderBase

TUSHARE_API = "https://api.tushare.pro"


class TushareProvider(DataProviderBase):
    """Tushare REST API 数据源适配器"""

    def __init__(self, bus: MessageBus, config: dict[str, Any], token: str):
        super().__init__(bus, config, source_name="tushare")
        self._token = token
        self._client: Any = None

        cb_cfg = config.get("circuit_breaker", {})
        self._cb = CircuitBreaker(
            name="tushare",
            failure_threshold=cb_cfg.get("failure_threshold", 3),
            recovery_timeout=cb_cfg.get("recovery_timeout", 60),
            half_open_max_requests=cb_cfg.get("half_open_max_requests", 2),
        )

    async def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=3, max_connections=5),
            )
        return self._client

    async def _post(self, api_name: str, params: dict = None, fields: str = "") -> dict:
        """POST 请求 Tushare API"""
        client = await self._get_client()
        body = {
            "api_name": api_name,
            "token": self._token,
            "params": params or {},
            "fields": fields,
        }
        resp = await client.post(TUSHARE_API, json=body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Tushare API error: {data.get('msg', 'unknown')}")
        return data.get("data", {})

    def _df_to_records(self, data: dict) -> list[dict]:
        """Tushare 返回 → list[dict]"""
        fields = data.get("fields", [])
        items = data.get("items", [])
        return [dict(zip(fields, row)) for row in items]

    async def health_check(self) -> bool:
        try:
            data = await self._post("daily", params={"ts_code": "000001.SZ", "start_date": "20260527", "end_date": "20260527"})
            return bool(data.get("items"))
        except Exception as e:
            logger.warning("Tushare 健康检查失败: {}", e)
            return False

    # ---- K线 ----

    async def fetch_kline(self, symbol: str, start: str, end: str, period: str = "daily") -> list[MarketData]:
        return await self._cb.call(
            self._do_fetch_kline, symbol, start, end, period,
            fallback=self._fallback_kline,
        )

    async def _do_fetch_kline(self, symbol: str, start: str, end: str, period: str = "daily") -> list[MarketData]:
        ts_code = self._to_ts_code(symbol)
        logger.info("Tushare 抓取 K 线: {} → {}, {} → {}", symbol, ts_code, start, end)

        data = await self._post("daily", params={
            "ts_code": ts_code, "start_date": start, "end_date": end,
        })

        records = self._df_to_records(data)
        result = []
        for r in records:
            result.append(MarketData(
                symbol=symbol,
                timestamp=datetime.strptime(r.get("trade_date", ""), "%Y%m%d"),
                open=float(r.get("open", 0)),
                high=float(r.get("high", 0)),
                low=float(r.get("low", 0)),
                close=float(r.get("close", 0)),
                volume=float(r.get("vol", 0)),
                amount=float(r.get("amount", 0)) / 1000 if r.get("amount") else None,
                source="tushare",
            ))

        logger.info("Tushare K 线: {} ({} 条)", symbol, len(result))
        if result:
            await self.cache_and_publish(result, symbol)
        return result

    async def _fallback_kline(self, symbol: str, start: str, end: str, period: str = "daily") -> list[MarketData]:
        cached = await self.bus.cache_get(f"market:raw:{symbol}")
        if cached:
            return [MarketData(
                symbol=r["symbol"], timestamp=datetime.fromisoformat(r["timestamp"]),
                open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                volume=r["volume"], amount=r.get("amount"), source="cache:tushare",
            ) for r in cached]
        return []

    # ---- 实时行情 ----

    async def fetch_realtime(self, symbol: str) -> Optional[dict[str, Any]]:
        return await self._cb.call(self._do_fetch_realtime, symbol, fallback=self._fallback_dict)

    async def _do_fetch_realtime(self, symbol: str) -> Optional[dict[str, Any]]:
        ts_code = self._to_ts_code(symbol)
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

        data = await self._post("daily", params={
            "ts_code": ts_code, "start_date": yesterday, "end_date": today,
        })
        records = self._df_to_records(data)
        if not records:
            return None

        latest = records[-1]
        prev = records[-2] if len(records) > 1 else latest
        price = float(latest.get("close", 0))
        prev_c = float(prev.get("close", 0))
        change_pct = (price - prev_c) / prev_c * 100 if prev_c else 0

        result = {
            "symbol": symbol,
            "price": price,
            "change_pct": round(change_pct, 2),
            "change": round(price - prev_c, 2),
            "volume": float(latest.get("vol", 0)),
            "amount": float(latest.get("amount", 0)) / 1000 if latest.get("amount") else 0,
            "high": float(latest.get("high", 0)),
            "low": float(latest.get("low", 0)),
            "open": float(latest.get("open", 0)),
            "pre_close": prev_c,
            "source": "tushare",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.cache_and_publish_dict(result, f"market:realtime:{symbol}")
        return result

    # ---- 资金流向 ----

    async def fetch_fund_flow(self, symbol: str) -> Optional[dict[str, Any]]:
        return await self._cb.call(self._do_fetch_fund_flow, symbol, fallback=self._fallback_dict)

    async def _do_fetch_fund_flow(self, symbol: str) -> Optional[dict[str, Any]]:
        ts_code = self._to_ts_code(symbol)
        today = datetime.now().strftime("%Y%m%d")

        data = await self._post("moneyflow", params={
            "ts_code": ts_code, "start_date": today, "end_date": today,
        })
        records = self._df_to_records(data)
        if not records:
            return None

        r = records[-1]
        result = {
            "symbol": symbol,
            "date": r.get("trade_date", ""),
            "main_net_inflow": float(r.get("buy_elg_amount", 0) or 0) + float(r.get("buy_lg_amount", 0) or 0),
            "main_net_inflow_pct": 0.0,
            "super_large_net": float(r.get("buy_elg_amount", 0) or 0),
            "super_large_pct": 0.0,
            "large_net": float(r.get("buy_lg_amount", 0) or 0),
            "large_pct": 0.0,
            "source": "tushare",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.cache_and_publish_dict(result, f"market:fundflow:{symbol}")
        return result

    # ---- 宏观指数 ----

    async def fetch_macro_indices(self) -> Optional[dict[str, Any]]:
        return await self._cb.call(self._do_fetch_macro_indices, fallback=self._fallback_dict)

    async def _do_fetch_macro_indices(self) -> Optional[dict[str, Any]]:
        logger.debug("Tushare 抓取宏观指标 (限频适配版)")

        results: dict[str, Any] = {"timestamp": datetime.now().isoformat(), "source": "tushare"}

        index_map = {
            "000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指",
        }
        today = datetime.now().strftime("%Y%m%d")
        indices_data = []

        for code, name in index_map.items():
            try:
                data = await self._post("index_daily", params={
                    "ts_code": code, "start_date": today, "end_date": today,
                })
                records = self._df_to_records(data)
                for r in records:
                    indices_data.append({
                        "code": code.replace(".SH", "").replace(".SZ", ""),
                        "name": name,
                        "close": float(r.get("close", 0)),
                        "涨跌幅": float(r.get("pct_chg", 0) or 0),
                        "volume": float(r.get("vol", 0) or 0),
                        "amount": float(r.get("amount", 0) or 0),
                        "date": r.get("trade_date", ""),
                    })
                await asyncio.sleep(1.2)
            except Exception as e:
                logger.warning("Tushare 指数 {} 失败: {}", code, e)

        results["indices"] = indices_data
        results["sectors"] = []

        await self.cache_and_publish_dict(results, "market:macro")
        return results

    async def _fallback_dict(self, *args: Any, **kwargs: Any) -> Optional[dict[str, Any]]:
        logger.warning("Tushare 数据请求降级")
        return None

    # ---- 工具 ----

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        """000001 → 000001.SZ, sh000001 → 000001.SH"""
        s = symbol.strip().upper()
        if s.startswith("SH"):
            return f"{s[2:]}.SH"
        if s.startswith("SZ"):
            return f"{s[2:]}.SZ"
        code = s.zfill(6)
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        return f"{code}.SZ"

    async def close(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Tushare 数据源已关闭")

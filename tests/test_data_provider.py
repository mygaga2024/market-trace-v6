"""
Market Trace V6.0 — 数据访问层单元测试
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.bus import MessageBus
from core.schema import MarketData
from data_provider.base import DataProviderBase
from data_provider.akshare_impl import AkShareProvider, _safe_float, pd_timestamp
from data_provider.fallback_handler import FallbackHandler


@pytest.fixture
def mock_bus() -> MagicMock:
    """模拟 Redis 消息总线"""
    bus = MagicMock(spec=MessageBus)
    bus.publish = AsyncMock(return_value=1)
    bus.cache_set = AsyncMock()
    bus.cache_get = AsyncMock(return_value=None)
    bus.health_check = AsyncMock(return_value=True)
    bus.xadd = AsyncMock(return_value="msg-001")
    return bus


@pytest.fixture
def ak_config() -> dict:
    return {
        "anti_scraping": {
            "delay": {"mean": 0.01, "std": 0.001, "min": 0.005},
            "user_agents": ["Test-UA/1.0"],
            "max_cache_age_seconds": 300,
        },
        "circuit_breaker": {
            "failure_threshold": 2,
            "recovery_timeout": 5,
            "half_open_max_requests": 1,
        },
    }


@pytest.fixture
def provider(mock_bus, ak_config) -> AkShareProvider:
    return AkShareProvider(mock_bus, ak_config)


class TestBaseProvider:
    """抽象基类测试"""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            DataProviderBase(MagicMock(), {}, "test")  # type: ignore

    def test_concrete_subclass_works(self, mock_bus):

        class ConcreteProvider(DataProviderBase):
            async def fetch_kline(self, symbol, start, end, period="daily"):
                return []

            async def fetch_realtime(self, symbol):
                return {"price": 10.0}

            async def fetch_fund_flow(self, symbol):
                return {"main_net_inflow": 100}

            async def fetch_macro_indices(self):
                return {"indices": []}

            async def health_check(self):
                return True

        p = ConcreteProvider(mock_bus, {}, "test_source")
        assert p.source_name == "test_source"

    @pytest.mark.asyncio
    async def test_cache_and_publish(self, mock_bus):
        class ConcreteProvider(DataProviderBase):
            async def fetch_kline(self, s, st, e, p="daily"): return []
            async def fetch_realtime(self, s): return {}
            async def fetch_fund_flow(self, s): return {}
            async def fetch_macro_indices(self): return {}
            async def health_check(self): return True

        p = ConcreteProvider(mock_bus, {"anti_scraping": {"max_cache_age_seconds": 60}}, "test")
        data = [
            MarketData(
                symbol="000001",
                timestamp=datetime(2026, 5, 20),
                open=10.0, high=11.0, low=9.5, close=10.8,
                volume=1000000, amount=10500000, source="test",
            )
        ]

        await p.cache_and_publish(data, "000001")

        mock_bus.cache_set.assert_called_once()
        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args[0]
        published = call_args[1]
        assert published["event"] == "DATA_UPDATED"
        assert published["symbol"] == "000001"
        assert published["records"] == 1


class TestAkShareSymbolNormalization:
    """股票代码标准化测试"""

    @pytest.mark.parametrize("input_sym,expected_market,expected_code", [
        ("000001", "sz", "000001"),
        ("600000", "sh", "600000"),
        ("sh000001", "sh", "000001"),
        ("SZ000001", "sz", "000001"),
        ("sh600000", "sh", "600000"),
        ("sz399001", "sz", "399001"),
        ("1", "sz", "000001"),
    ])
    def test_normalize_symbol(self, input_sym, expected_market, expected_code):
        market, code = DataProviderBase._normalize_symbol(input_sym)
        assert market == expected_market
        assert code == expected_code


class TestAkShareStandardization:
    """数据标准化测试"""

    def test_standardize_kline(self, provider):
        df = pd.DataFrame({
            "日期": pd.to_datetime(["2026-05-20", "2026-05-21"]),
            "开盘": [10.0, 10.5],
            "最高": [11.0, 11.5],
            "最低": [9.5, 10.2],
            "收盘": [10.8, 11.2],
            "成交量": [1000000.0, 1200000.0],
            "成交额": [10500000.0, 13000000.0],
        })

        records = provider._standardize_kline(df, "000001")
        assert len(records) == 2
        assert all(isinstance(r, MarketData) for r in records)
        assert records[0].symbol == "000001"
        assert records[0].source == "akshare"
        assert records[0].open == 10.0
        assert records[0].close == 10.8
        assert records[0].amount == 10500000.0

    def test_standardize_kline_missing_columns(self, provider):
        df = pd.DataFrame({
            "日期": pd.to_datetime(["2026-05-20"]),
            "开盘": [10.0],
            "最高": [11.0],
            "最低": [9.5],
            "收盘": [10.8],
            "成交量": [1000000.0],
        })
        records = provider._standardize_kline(df, "000001")
        assert len(records) == 1
        assert records[0].amount is None


class TestSafeFloat:
    """安全浮点转换测试"""

    def test_normal_float(self):
        row = pd.Series({"col": 123.45})
        assert _safe_float(row, "col") == 123.45

    def test_none_value(self):
        row = pd.Series({"col": None})
        assert _safe_float(row, "col") == 0.0

    def test_dash_string(self):
        row = pd.Series({"col": "-"})
        assert _safe_float(row, "col") == 0.0

    def test_empty_string(self):
        row = pd.Series({"col": ""})
        assert _safe_float(row, "col") == 0.0

    def test_custom_default(self):
        row = pd.Series({"col": None})
        assert _safe_float(row, "col", default=-1.0) == -1.0


class TestPdTimestamp:
    """时间戳转换测试"""

    def test_pandas_timestamp(self):
        ts = pd.Timestamp("2026-05-20 15:30:00")
        result = pd_timestamp(ts)
        assert isinstance(result, datetime)
        assert result.year == 2026

    def test_string(self):
        result = pd_timestamp("2026-05-20")
        assert isinstance(result, datetime)
        assert result.month == 5

    def test_numeric_timestamp(self):
        result = pd_timestamp(1.0)
        assert isinstance(result, datetime)


class TestAkShareProvider:
    """AkShare 数据源集成测试"""

    @pytest.mark.asyncio
    async def test_random_delay(self, provider):
        t0 = datetime.now()
        await provider._random_delay()
        elapsed = (datetime.now() - t0).total_seconds()
        assert elapsed > 0, "延迟应 > 0"

    def test_rotate_ua(self, provider):
        ua = provider._rotate_ua()
        assert ua == "Test-UA/1.0"

    @pytest.mark.asyncio
    async def test_fetch_kline_cache_publish(self, provider):
        df = pd.DataFrame({
            "日期": pd.to_datetime(["2026-05-20"]),
            "开盘": [10.0], "最高": [11.0], "最低": [9.5], "收盘": [10.8],
            "成交量": [1000000.0], "成交额": [10500000.0],
        })

        with patch("akshare.stock_zh_a_hist_tx", side_effect=RuntimeError("mocked unavailable")), \
             patch("akshare.stock_zh_a_hist", return_value=df):
            records = await provider._do_fetch_kline("000001", "20260501", "20260520")
            assert len(records) == 1
            assert records[0].symbol == "000001"

            provider.bus.cache_set.assert_called()
            provider.bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_fallback_kline_cache_miss(self, provider):
        provider.bus.cache_get.return_value = None
        records = await provider._fallback_fetch_kline("000001", "", "")
        assert records == []

    @pytest.mark.asyncio
    async def test_fallback_kline_cache_hit(self, provider):
        cached = [{
            "symbol": "000001",
            "timestamp": "2026-05-20T00:00:00",
            "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8,
            "volume": 1000000, "amount": 10500000, "source": "akshare",
        }]
        provider.bus.cache_get.return_value = cached
        records = await provider._fallback_fetch_kline("000001", "", "")
        assert len(records) == 1
        assert records[0].source == "cache:akshare"

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self, provider):
        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("模拟连接失败")

        with pytest.raises(ConnectionError):
            await provider._cb.call(failing_func)

        assert call_count == 1
        assert provider._cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_health_check(self, provider):
        df = pd.DataFrame({"代码": ["000001"], "名称": ["平安银行"], "最新价": [10.0]})
        with patch("akshare.stock_zh_a_spot_em", return_value=df):
            result = await provider.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_close(self, provider):
        await provider.close()
        assert provider._running is False


class TestFallbackHandler:
    """降级处理器测试"""

    @pytest.fixture
    def fallback(self, mock_bus) -> FallbackHandler:
        return FallbackHandler(mock_bus, {"anti_scraping": {"max_cache_age_seconds": 300}})

    @pytest.mark.asyncio
    async def test_primary_succeeds(self, fallback, mock_bus, ak_config):
        class MockPrimary(DataProviderBase):
            async def fetch_kline(self, s, st, e, p="daily"): return [MarketData(symbol=s, timestamp=datetime.now(), open=1, high=1, low=1, close=1, volume=1, source="mock")]
            async def fetch_realtime(self, s): return {}
            async def fetch_fund_flow(self, s): return {}
            async def fetch_macro_indices(self): return {}
            async def health_check(self): return True

        primary = MockPrimary(mock_bus, ak_config, "mock_source")
        result = await fallback.try_fetch(primary, "fetch_kline", "000001", "20260101", "20260520", symbol="000001")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].symbol == "000001"
        assert result[0].source == "mock"

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_cache(self, fallback, mock_bus, ak_config):
        class MockPrimary(DataProviderBase):
            async def fetch_kline(self, s, st, e, p="daily"): raise RuntimeError("模拟失败")
            async def fetch_realtime(self, s): return {}
            async def fetch_fund_flow(self, s): return {}
            async def fetch_macro_indices(self): return {}
            async def health_check(self): return True

        primary = MockPrimary(mock_bus, ak_config, "mock_source")

        cached = [{"symbol": "000001", "timestamp": datetime.now().isoformat(), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        mock_bus.cache_get.return_value = cached

        result = await fallback.try_fetch(primary, "fetch_kline", "000001", "20260101", "20260520", symbol="000001")
        assert isinstance(result, list)
        assert result[0].get("cached") is True

    @pytest.mark.asyncio
    async def test_cache_miss_signals_missing(self, fallback, mock_bus, ak_config):
        class MockPrimary(DataProviderBase):
            async def fetch_kline(self, s, st, e, p="daily"): raise RuntimeError("模拟失败")
            async def fetch_realtime(self, s): return {}
            async def fetch_fund_flow(self, s): return {}
            async def fetch_macro_indices(self): return {}
            async def health_check(self): return True

        primary = MockPrimary(mock_bus, ak_config, "mock_source")
        mock_bus.cache_get.return_value = None

        result = await fallback.try_fetch(primary, "fetch_kline", "000001", "20260101", "20260520", symbol="000001")
        assert result is None

        publish_calls = [c[0][1] for c in mock_bus.publish.call_args_list]
        missing_events = [e for e in publish_calls if e.get("event") == "DATA_MISSING"]
        assert len(missing_events) == 1
        assert missing_events[0]["symbol"] == "000001"

    @pytest.mark.asyncio
    async def test_consecutive_failure_becomes_critical(self, fallback, mock_bus, ak_config):
        class MockPrimary(DataProviderBase):
            async def fetch_kline(self, s, st, e, p="daily"): raise RuntimeError("模拟失败")
            async def fetch_realtime(self, s): return {}
            async def fetch_fund_flow(self, s): return {}
            async def fetch_macro_indices(self): return {}
            async def health_check(self): return True

        primary = MockPrimary(mock_bus, ak_config, "mock_source")
        mock_bus.cache_get.return_value = None

        for _ in range(12):
            await fallback.try_fetch(primary, "fetch_kline", "000001", "20260101", "20260520", symbol="000001")

        publish_calls = [c[0][1] for c in mock_bus.publish.call_args_list]
        missing_events = [e for e in publish_calls if e.get("event") == "DATA_MISSING"]
        last_event = missing_events[-1]
        assert last_event["severity"] == "critical"
        assert last_event["consecutive_failures"] >= 12

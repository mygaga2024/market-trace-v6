"""
Market Trace V6.0 — 核心诊股服务
技术分析、多策略信号检测、LLM决策输入构建
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import numpy as np
from fastapi import HTTPException
from loguru import logger

from core.strategies import STRATEGIES, _calc_rsi, _calc_ma, _calc_atr, _calc_ema, _calc_macd


# ── 模块级 httpx 客户端，供腾讯实时价复用（避免每次诊股都创建新连接）──
_tencent_client: httpx.AsyncClient | None = None


def _get_tencent_client() -> httpx.AsyncClient:
    global _tencent_client
    if _tencent_client is None or _tencent_client.is_closed:
        _tencent_client = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
        )
    return _tencent_client


# ── 增强技术指标 ──

def _calc_bollinger(closes: np.ndarray, period: int = 20, nbdev: float = 2.0) -> dict:
    if len(closes) < period:
        return {"upper": None, "middle": None, "lower": None, "bandwidth": None}
    mid = float(np.mean(closes[-period:]))
    std = float(np.std(closes[-period:]))
    upper = mid + nbdev * std
    lower = mid - nbdev * std
    bandwidth = (upper - lower) / mid if mid > 0 else 0
    return {
        "upper": round(upper, 2), "middle": round(mid, 2), "lower": round(lower, 2),
        "bandwidth": round(bandwidth, 4),
        "position": round((closes[-1] - lower) / (upper - lower), 4) if upper > lower else 0.5,
    }


# （_calc_atr 已迁移到 core/strategies.py 统一复用）


def _calc_kdj(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
              period: int = 9, smooth: int = 3) -> dict:
    if len(closes) < period:
        return {"k": 50, "d": 50, "j": 50}
    k, d = 50.0, 50.0
    for i in range(period - 1, len(closes)):
        high_n = float(np.max(highs[i - period + 1:i + 1]))
        low_n = float(np.min(lows[i - period + 1:i + 1]))
        rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if high_n > low_n else 50
        k = (k * (smooth - 1) + rsv) / smooth
        d = (d * (smooth - 1) + k) / smooth
    j = 3 * k - 2 * d
    return {"k": round(k, 2), "d": round(d, 2), "j": round(j, 2)}


def _find_support_resistance(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                             lookback: int = 60) -> dict:
    """简化支撑阻力位：最近N日高低点"""
    n = min(lookback, len(closes))
    high = float(np.max(highs[-n:]))
    low = float(np.min(lows[-n:]))
    return {
        "resistance": round(high, 2),
        "support": round(low, 2),
        "pivot": round((high + low + closes[-1]) / 3, 2),
    }


# ── 核心诊股 ──

async def analyze_single(
    symbol: str, bus, config: dict, llm_chain,
    prefetch_tp=None, prefetch_ap=None,
) -> dict:
    """全面诊股：数据获取→技术分析→策略信号→LLM决策"""
    cached = None
    provider_cfg = [p for p in config.get("data_providers", []) if p.get("enabled")]
    tushare_token = next((p.get("token") for p in provider_cfg if p.get("name") == "tushare" and p.get("token")), None)
    cache_key = f"market:raw:{symbol}"

    # 1) 优先读缓存
    if bus:
        cached = await bus.cache_get(cache_key)

    # 2) Tushare 主力源
    if not cached and tushare_token and prefetch_tp:
        try:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            klines = await prefetch_tp.fetch_kline(symbol, start_date, datetime.now().strftime("%Y%m%d"))
            if klines:
                last_date = klines[-1].timestamp.date()
                if (datetime.now().date() - last_date).days <= 2:
                    cached = [{"close": k.close, "open": k.open, "high": k.high, "low": k.low,
                               "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()}
                              for k in klines]
                    if bus:
                        await bus.cache_set(cache_key, cached, ttl=3600)
                else:
                    logger.info("Tushare K线过旧({}), 降级", last_date)
        except Exception as e:
            logger.debug("Tushare K线失败: {}", e)

    # 3) AkShare 备用
    if not cached:
        try:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            ap = prefetch_ap
            if ap is None:
                from data_provider.akshare_impl import AkShareProvider
                ap = AkShareProvider(bus, config)
            klines = await ap.fetch_kline(symbol, start_date, datetime.now().strftime("%Y%m%d"))
            if klines:
                cached = [{"close": k.close, "open": k.open, "high": k.high, "low": k.low,
                           "volume": k.volume, "amount": k.amount, "timestamp": k.timestamp.isoformat()}
                          for k in klines]
                if bus:
                    await bus.cache_set(cache_key, cached, ttl=3600)
        except Exception as e:
            logger.debug("AkShare K线失败: {}", e)

    if not cached or len(cached) < 5:
        raise HTTPException(400, f"股票 {symbol} 数据不足，至少需要5条K线")

    # 4) 腾讯实时价修正（浅拷贝避免污染缓存）
    cached = list(cached)
    prev_close = await _apply_tencent_quote(symbol, cached)

    closes = np.array([float(r["close"]) for r in cached])
    highs = np.array([float(r["high"]) for r in cached])
    lows = np.array([float(r["low"]) for r in cached])
    volumes = np.array([float(r["volume"]) for r in cached])

    # ── 技术指标 ──
    price = float(closes[-1])
    # 优先使用腾讯返回的官方昨收价计算涨跌幅，与持仓列表(Sina)保持一致
    if prev_close and prev_close > 0:
        change_pct = round((price - prev_close) / prev_close * 100, 2)
    else:
        prev_k = float(closes[-2]) if len(closes) > 1 else price
        change_pct = round((price - prev_k) / prev_k * 100, 2) if prev_k else 0

    ma5 = round(_calc_ma(closes, 5), 2) if len(closes) >= 5 else None
    ma10 = round(_calc_ma(closes, 10), 2) if len(closes) >= 10 else None
    ma20 = round(_calc_ma(closes, 20), 2) if len(closes) >= 20 else None
    ma60 = round(_calc_ma(closes, 60), 2) if len(closes) >= 60 else None

    rsi = round(_calc_rsi(closes, 14), 2) if len(closes) >= 15 else None
    macd = _calc_macd(closes)
    bollinger = _calc_bollinger(closes)
    atr = round(_calc_atr(highs, lows, closes), 2)
    kdj = _calc_kdj(highs, lows, closes)
    sr_levels = _find_support_resistance(highs, lows, closes)

    vol_ratio = round(float(volumes[-1] / np.mean(volumes[:-1])), 2) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0
    avg_vol_5 = round(float(np.mean(volumes[-5:])), 0) if len(volumes) >= 5 else 0
    avg_vol_20 = round(float(np.mean(volumes[-20:])), 0) if len(volumes) >= 20 else 0

    # 趋势判断：优先用 ma60，不足时回退到 ma5/ma20（任一缺失则不参与比较）
    trend = "sideways"
    if ma20 is not None and ma5 is not None:
        if ma60 and ma5 > ma20 > ma60:
            trend = "bullish"
        elif ma60 and ma5 < ma20 < ma60:
            trend = "bearish"
        elif ma5 > ma20:
            trend = "bullish"
        elif ma5 < ma20:
            trend = "bearish"
        elif ma10 is not None:
            if ma5 > ma10:
                trend = "bullish"
            elif ma5 < ma10:
                trend = "bearish"

    indicators = {
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "rsi": rsi, "macd": macd,
        "bollinger": bollinger, "atr": atr, "kdj": kdj,
        "support_resistance": sr_levels,
        "vol_ratio": vol_ratio, "avg_vol_5": avg_vol_5, "avg_vol_20": avg_vol_20,
        "trend": trend,
    }

    # ── 策略信号检测(复用统一策略) ──
    strategy_signals: list[dict] = []
    for name, info in STRATEGIES.items():
        try:
            kwargs = info.get("params", {}).copy()
            hit = info["check"](closes, highs, volumes, **kwargs)
            if hit:
                strategy_signals.append({
                    "strategy": name,
                    "label": info["label"],
                    "type": "BUY" if name != "risk" else "SELL",
                    "direction": "bullish" if name != "risk" else "bearish",
                    "strength": 0.7,
                })
                logger.info("策略命中: {} {} (RSI={})", symbol, name, rsi if rsi is not None else "N/A")
        except Exception:
            logger.warning("策略检测异常 strategy={}", name, exc_info=True)

    logger.info("诊股 {}: trend={} RSI={} 策略命中{}个",
                symbol, trend, rsi if rsi is not None else "N/A", len(strategy_signals))

    # ── Signal Agent 实时信号(从缓存读取) ──
    signal_agent_signals: list[dict] = []
    signal_agent_confidence = 0.5
    if bus:
        try:
            sig_cache = await bus.cache_get(f"reports:signal:{symbol}")
            if sig_cache and isinstance(sig_cache, dict):
                signal_agent_signals = sig_cache.get("signals", [])
                signal_agent_confidence = sig_cache.get("confidence", 0.5)
        except Exception:
            pass

    # ── 量价异动检测 ──
    trace_signals: list[dict] = []
    if len(volumes) >= 3:
        avg = float(np.mean(volumes[:-1]))
        last = float(volumes[-1])
        if avg > 0 and last > avg * 2.0:
            _dir = "bullish" if closes[-1] > closes[-2] else "bearish"
            trace_signals.append({"type": "VOLUME_SPIKE", "direction": _dir,
                                   "ratio": round(last / avg, 2), "strength": min(0.8, (last / avg - 1) * 0.3)})
    if len(closes) >= 5 and len(volumes) >= 5:
        pc = (closes[-1] - closes[-5]) / closes[-5]
        avg5 = float(np.mean(volumes[-5:-1]))
        vc = (volumes[-1] - avg5) / avg5 if avg5 > 0 else 0
        if pc > 0.03 and vc < -0.2:
            trace_signals.append({"type": "BULLISH_DIVERGENCE_WEAK_VOLUME", "direction": "bearish",
                                   "note": "价涨量缩，上涨乏力", "strength": 0.5})
        elif pc < -0.03 and vc > 0.5:
            trace_signals.append({"type": "BEARISH_DIVERGENCE_HIGH_VOLUME", "direction": "bearish",
                                    "note": "价跌量增，恐慌抛售", "strength": 0.6})

    logger.info("诊股 {}: 趋势={} RSI={:.1f} 策略={}个 异动={}个 Agent信号={}个",
                symbol, trend, rsi, len(strategy_signals), len(trace_signals), len(signal_agent_signals))

    # ── 宏观RAI ──
    macro_rai = None  # 缓存缺失时不兜底 0.5，显式标注数据缺失（1.3.7）
    macro_data = {}
    if bus:
        mc = await bus.cache_get("market:macro")
        if mc and isinstance(mc, dict):
            macro_rai = mc.get("risk_appetite_index")
            macro_data = mc

    # ── 构建 AI 决策输入 ──
    decision = None
    if llm_chain:
        try:
            from core.schema import AgentReport, AgentName
            from core.chief_decision import build_chief_decision, evaluate_risk_sync

            # Macro报告: 携带完整RAI数据
            interp = macro_data.get("interpretation", {})
            components = macro_data.get("components", {})
            raw_indices = macro_data.get("indices", [])
            macro_reports_data = {
                "risk_appetite_index": macro_rai,
                "rai_available": macro_rai is not None,
                "interpretation": interp,
                "components": components,
                "indices_summary": [
                    {"name": i.get("name", ""), "change": i.get("涨跌幅", 0)}
                    for i in raw_indices[-5:]
                ] if raw_indices else [],
            }

            # Signal报告: 技术指标 + 策略命中 + Signal Agent实时信号
            signal_report_data = {
                "indicators": indicators,
                "signals": strategy_signals,
                "agent_signals": signal_agent_signals,
                "reliability": signal_agent_confidence,
            }

            # Trace报告: 量价信号 + 资金流向
            trace_report_data = {
                "signals": trace_signals,
                "fund_flow": {},
                "direction": "bullish" if change_pct > 0 else "bearish" if change_pct < 0 else "neutral",
            }

            reports = {
                "macro": AgentReport(
                    agent=AgentName.MACRO,
                    summary=(
                        f"RAI={macro_rai:.2f} ({interp.get('regime', '未知')})"
                        if macro_rai is not None else "宏观数据缺失"
                    ),
                    data=macro_reports_data,
                    confidence=abs(macro_rai - 0.5) * 2 if macro_rai is not None else 0.0,
                ),
                "signal": AgentReport(
                    agent=AgentName.SIGNAL,
                    summary=f"价格{price:.2f} {trend} RSI={rsi} 策略命中{len(strategy_signals)}个 SignalAgent信号{len(signal_agent_signals)}个",
                    data=signal_report_data,
                    confidence=min(1.0, signal_agent_confidence),
                ),
                "trace": AgentReport(
                    agent=AgentName.TRACE,
                    summary=f"量比{vol_ratio}x 异动{len(trace_signals)}个",
                    data=trace_report_data,
                    confidence=min(1.0, len(trace_signals) * 0.3 + 0.3),
                ),
            }

            risk_severity, risk_reason = evaluate_risk_sync(reports, daily_change_pct=change_pct)
            dec = await build_chief_decision(
                reports=reports,
                llm_chain=llm_chain,
                risk_severity=risk_severity,
                risk_reason=risk_reason,
            )
            decision = {
                "action": dec.action.value, "confidence": dec.confidence,
                "reasoning": dec.reasoning, "provider": dec.provider_label,
                "provider_status": dec.provider_status.value if hasattr(dec.provider_status, 'value') else str(dec.provider_status),
            }
        except Exception as e:
            logger.debug("LLM 分析异常: {}", e)

    # ── 组装返回 ──
    latest_ts = cached[-1]["timestamp"] if cached else None
    from services.prefetch import get_stock_name
    stock_name = await get_stock_name(symbol, bus)

    trace_output = [{"type": s["type"], "direction": s["direction"], "strength": s.get("strength", 0)}
                    for s in trace_signals]

    # 简化的策略命中列表
    strategy_hits = [{"strategy": s["strategy"], "label": s["label"], "type": s["type"]}
                     for s in strategy_signals]

    return {
        "symbol": symbol, "name": stock_name, "price": price, "change_pct": change_pct,
        "indicators": indicators,
        "trace_signals": trace_output,
        "strategy_hits": strategy_hits,
        "macro_rai": macro_rai,
        "trend": trend,
        "decision": decision,
        "data_timestamp": latest_ts,
        "data_source": "tushare" if tushare_token else "akshare",
    }


async def _apply_tencent_quote(symbol: str, cached: list[dict]) -> float | None:
    """腾讯行情API修正最后一根K线的收盘价，返回官方昨收价(用于计算涨跌幅)"""
    prev_close = None
    try:
        ts_prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
        url = f"http://qt.gtimg.cn/q={ts_prefix}{symbol}"
        client = _get_tencent_client()
        resp = await client.get(url)
        text = resp.text
        if "~" not in text:
            return None
        fields = text.split("~")
        if len(fields) >= 5:
            live_price = float(fields[3])
            try:
                prev_close = float(fields[4]) if fields[4] else None
            except (ValueError, IndexError):
                pass
            if live_price > 0 and abs(live_price - float(cached[-1]["close"])) > 0.001:
                cached[-1] = {
                    **cached[-1],
                    "close": live_price,
                    "high": max(float(cached[-1]["high"]), live_price),
                    "low": min(float(cached[-1]["low"]), live_price),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
    except Exception as e:
        logger.debug("腾讯实时价获取失败 ({}): {}", symbol, e)
    return prev_close


# ── K线渲染 ──

def render_kline_svg(closes: list[float]) -> str:
    w, h = 200, 40
    mn, mx = min(closes), max(closes)
    rng = max(mx - mn, 0.01)
    step = w / max(len(closes) - 1, 1)
    color = "#3fb950" if closes[-1] >= closes[0] else "#f85149"
    points = " ".join(f"{i*step:.1f},{h - (c - mn)/rng*h*0.8 - h*0.1:.1f}" for i, c in enumerate(closes))
    poly = " ".join(f"{i*step:.1f},{h}" for i in range(len(closes)))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" fill="#0d1117" rx="4"/><polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5"/><polygon points="0,{h} {poly} {w},{h}" fill="{color}" opacity="0.1"/></svg>'


def build_kline_json(cached: list[dict], symbol: str) -> dict:
    bars = []
    for r in cached[-60:]:
        bars.append({
            "time": r.get("timestamp", "")[:10],
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": int(float(r["volume"])),
        })
    return {"symbol": symbol, "bars": bars, "count": len(bars)}

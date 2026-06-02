"""
Market Trace V6.0 — 核心分析服务
诊股逻辑、选股策略定义、K线渲染
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
import numpy as np
from fastapi import HTTPException
from loguru import logger


# ─────────────────────────────────────────────
# 策略定义（命名函数替代 lambda，可读性 + 可测试性）
# ─────────────────────────────────────────────

def _strategy_breakout(c: list, h: list, v: list) -> bool:
    """强势突破：突破20日高点 + 放量 + 收阳"""
    return (len(c) >= 20 and c[-1] > max(h[-20:-1])
            and v[-1] > np.mean(v[-20:-1]) * 1.5
            and len(c) >= 2 and c[-1] > c[-2])


def _strategy_oversold(c: list, h: list, v: list) -> bool:
    """超跌反弹：RSI < 35 + 5日跌幅 > 3%"""
    return (len(c) >= 14 and _calc_rsi14(c) < 35
            and (c[-1] - c[-5]) / c[-5] < -0.03)


def _strategy_strength(c: list, h: list, v: list) -> bool:
    """主力介入：量能翻倍(20日均量) + 5日涨幅>2%"""
    return (len(c) >= 20 and v[-1] > np.mean(v[-20:-1]) * 2
            and (c[-1] - c[-5]) / c[-5] > 0.02)


def _strategy_risk(c: list, h: list, v: list) -> bool:
    """风险预警：RSI > 70 + 价格低于20日前"""
    return (len(c) >= 14 and _calc_rsi14(c) > 70
            and c[-1] < c[-20])


def _strategy_ma_golden_cross(c: list, h: list, v: list) -> bool:
    """均线金叉：MA5 上穿 MA20 + 放量"""
    if len(c) < 20:
        return False
    ma5 = _calc_ma_val(c, 5)
    ma20 = _calc_ma_val(c, 20)
    return bool(ma5[-1] > ma20[-1]
                and ma5[-2] <= ma20[-2]
                and v[-1] > np.mean(v[-20:-1]) * 1.2)


def _strategy_volume_breakout(c: list, h: list, v: list) -> bool:
    """放量突破：3倍量能 + 5日涨幅 > 5%"""
    return (len(c) >= 5 and v[-1] > np.mean(v[-20:-1]) * 3
            and (c[-1] - c[-5]) / c[-5] > 0.05)


def _strategy_rsi_reversal(c: list, h: list, v: list) -> bool:
    """RSI反转：RSI < 30 + RSI 回升 > 3"""
    if len(c) < 14:
        return False
    rsi_now = _calc_rsi14(c)
    rsi_prev = _calc_rsi_val(c, 2)
    return bool(rsi_now < 30 and (rsi_now - rsi_prev) > 3)


STRATEGIES: dict[str, tuple[Any, str]] = {
    "breakout": (_strategy_breakout, "强势突破"),
    "oversold": (_strategy_oversold, "超跌反弹"),
    "strength": (_strategy_strength, "主力介入"),
    "risk": (_strategy_risk, "风险预警"),
    "ma_golden_cross": (_strategy_ma_golden_cross, "均线金叉"),
    "volume_breakout": (_strategy_volume_breakout, "放量突破"),
    "rsi_reversal": (_strategy_rsi_reversal, "RSI反转"),
}


# ─────────────────────────────────────────────
# 辅助计算函数
# ─────────────────────────────────────────────

def _calc_rsi14(closes) -> float:
    from agents.signal_agent import SignalAgent
    r = SignalAgent._calc_rsi(np.array(closes), 14)
    return float(r[-1]) if r is not None and len(r) > 0 else 50


def _calc_ma_val(closes, period) -> np.ndarray:
    from agents.signal_agent import SignalAgent
    return SignalAgent._calc_ma(np.array(closes), period)


def _calc_rsi_val(closes, days_ago) -> float:
    from agents.signal_agent import SignalAgent
    r = SignalAgent._calc_rsi(np.array(closes), 14)
    if r is not None and len(r) > days_ago:
        return float(r[-days_ago - 1]) if len(r) > days_ago else float(r[0])
    return 50


# ─────────────────────────────────────────────
# 核心诊股逻辑
# ─────────────────────────────────────────────

async def analyze_single(
    symbol: str,
    bus,
    config: dict,
    llm_chain,
    prefetch_tp=None,
    prefetch_ap=None,
) -> dict:
    """核心分析逻辑：Tushare(主力)→AkShare(备用)→Redis缓存降级→算指标→调LLM"""
    cached = None
    provider_cfg = [p for p in config.get("data_providers", []) if p.get("enabled")]
    tushare_token = next((p.get("token") for p in provider_cfg if p.get("name") == "tushare" and p.get("token")), None)
    cache_key = f"market:raw:{symbol}"

    # 1) Tushare 主力源
    if tushare_token and prefetch_tp:
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
                    logger.info("Tushare K线过旧({}), 降级到AkShare", last_date)
        except Exception as e:
            logger.debug("Tushare K线获取失败: {}", e)

    # 2) AkShare 备用
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
            logger.debug("AkShare K线获取失败: {}", e)

    # 3) 降级到 Redis 缓存
    if not cached and bus:
        cached = await bus.cache_get(cache_key)

    # 4) 盘中实时报价修正：腾讯行情API
    if cached:
        try:
            ts_prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
            url = f"http://qt.gtimg.cn/q={ts_prefix}{symbol}"
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as tc:
                resp = await tc.get(url)
                text = resp.text
                if "~" not in text:
                    raise ValueError("非行情数据响应")
            fields = text.split("~")
            if len(fields) >= 4:
                live_price = float(fields[3])
                prev_close = float(fields[4]) if len(fields) > 4 else float(cached[-1]["close"])
                if live_price > 0 and abs(live_price - float(cached[-1]["close"])) > 0.001:
                    logger.info("腾讯实时价: {} = {} (前收: {})", symbol, live_price, prev_close)
                    cached[-1] = {
                        **cached[-1],
                        "close": live_price,
                        "high": max(float(cached[-1]["high"]), live_price),
                        "low": min(float(cached[-1]["low"]), live_price),
                    }
        except Exception as e:
            logger.debug("腾讯实时价获取失败 ({}): {}", symbol, e)

    if not cached or len(cached) < 5:
        raise HTTPException(400, f"股票 {symbol} 数据不足，至少需要5条K线")

    closes = np.array([float(r["close"]) for r in cached])
    highs = np.array([float(r["high"]) for r in cached])
    lows = np.array([float(r["low"]) for r in cached])
    volumes = np.array([float(r["volume"]) for r in cached])

    from agents.signal_agent import SignalAgent

    ma5 = round(float(SignalAgent._calc_ma(closes, 5)[-1]), 2) if len(closes) >= 5 else None
    ma10 = round(float(SignalAgent._calc_ma(closes, 10)[-1]), 2) if len(closes) >= 10 else None
    ma20 = round(float(SignalAgent._calc_ma(closes, 20)[-1]), 2) if len(closes) >= 20 else None

    rsi_vals = SignalAgent._calc_rsi(closes, 14)
    rsi = round(float(rsi_vals[-1]), 2) if rsi_vals is not None and len(rsi_vals) > 0 and not np.isnan(rsi_vals[-1]) else None

    sig_cfg = config.get("agents", {}).get("signal", {})
    _macd_fast = sig_cfg.get("macd_fast", 12)
    _macd_slow = sig_cfg.get("macd_slow", 26)
    _macd_signal = sig_cfg.get("macd_signal", 9)
    macd = {}
    if len(closes) >= _macd_slow + _macd_signal:
        ema_fast = SignalAgent._calc_ema(closes, _macd_fast)
        ema_slow = SignalAgent._calc_ema(closes, _macd_slow)
        dif = ema_fast - ema_slow
        dea = SignalAgent._calc_ema(dif[~np.isnan(dif)], _macd_signal) if len(dif[~np.isnan(dif)]) > 0 else np.array([])
        if len(dea) > 0:
            dea_full = np.full(len(dif), np.nan)
            dea_full[len(dif) - len(dea):] = dea
            hist = 2 * (dif - dea_full)
            macd = {
                "dif": round(float(dif[-1]), 4) if not np.isnan(dif[-1]) else None,
                "dea": round(float(dea_full[-1]), 4) if not np.isnan(dea_full[-1]) else None,
                "histogram": round(float(hist[-1]), 4) if not np.isnan(hist[-1]) else None,
            }

    price = closes[-1]
    prev = closes[-2] if len(closes) > 1 else price
    change_pct = round((price - prev) / prev * 100, 2) if prev else 0

    vol_ratio = round(float(volumes[-1] / np.mean(volumes[:-1])), 2) if len(volumes) > 1 and np.mean(volumes[:-1]) > 0 else 1.0

    # Trace 信号检测
    trace_signals = []
    if len(volumes) >= 3:
        avg_vol = float(np.mean(volumes[:-1]))
        last_vol = float(volumes[-1])
        if avg_vol > 0 and last_vol > avg_vol * 2.0:
            _dir = "bullish" if closes[-1] > closes[-2] else "bearish"
            trace_signals.append({"type": "VOLUME_SPIKE", "direction": _dir,
                                  "ratio": round(last_vol / avg_vol, 2),
                                  "strength": min(0.8, (last_vol / avg_vol - 1) * 0.3)})
    if len(closes) >= 5 and len(volumes) >= 5:
        _pc = (closes[-1] - closes[-5]) / closes[-5]
        _avg5 = float(np.mean(volumes[-5:-1]))
        _vc = (volumes[-1] - _avg5) / _avg5 if _avg5 > 0 else 0
        if _pc > 0.03 and _vc < -0.2:
            trace_signals.append({"type": "BULLISH_DIVERGENCE_WEAK_VOLUME", "direction": "bearish",
                                  "note": "价涨量缩，上涨乏力", "strength": 0.5})
        elif _pc < -0.03 and _vc > 0.5:
            trace_signals.append({"type": "BEARISH_DIVERGENCE_HIGH_VOLUME", "direction": "bearish",
                                  "note": "价跌量增，恐慌抛售", "strength": 0.6})

    macro_rai = 0.5
    if bus:
        mc = await bus.cache_get("market:macro")
        if mc and isinstance(mc, dict):
            macro_rai = mc.get("risk_appetite_index", 0.5)

    decision = None
    if llm_chain:
        try:
            from core.schema import AgentReport, AgentName, DecisionAction
            reports = {
                "macro": AgentReport(agent=AgentName.MACRO, summary=f"RAI={macro_rai:.2f}",
                    data={"risk_appetite_index": macro_rai}, confidence=abs(macro_rai - 0.5) * 2),
                "signal": AgentReport(agent=AgentName.SIGNAL, summary=f"价格{price}",
                    data={"indicators": {"rsi": rsi, "macd": macd}, "signals": []}, confidence=0.5),
                "trace": AgentReport(agent=AgentName.TRACE, summary="量价分析",
                    data={"signals": trace_signals, "direction": "neutral"}, confidence=0.5),
            }
            dec = await llm_chain.analyze(reports)
            decision = {
                "action": dec.action.value, "confidence": dec.confidence,
                "reasoning": dec.reasoning, "provider": dec.provider_label,
            }
        except Exception as e:
            logger.debug("LLM 分析异常: {}", e)

    latest_ts = cached[-1]["timestamp"] if cached else None
    return {
        "symbol": symbol, "price": float(price), "change_pct": change_pct,
        "indicators": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "macd": macd, "rsi": rsi, "vol_ratio": vol_ratio},
        "trace_signals": [{"type": s["type"], "direction": s["direction"], "strength": s.get("strength", 0)} for s in trace_signals],
        "macro_rai": macro_rai, "decision": decision,
        "data_timestamp": latest_ts, "data_source": "tushare" if tushare_token else "akshare",
    }


# ─────────────────────────────────────────────
# K线渲染
# ─────────────────────────────────────────────

def render_kline_svg(closes: list[float]) -> str:
    """生成 K 线迷你 SVG 图"""
    w, h = 200, 40
    mn, mx = min(closes), max(closes)
    rng = max(mx - mn, 0.01)
    step = w / max(len(closes) - 1, 1)
    color = "#3fb950" if closes[-1] >= closes[0] else "#f85149"
    points = " ".join(f"{i*step:.1f},{h - (c - mn)/rng*h*0.8 - h*0.1:.1f}" for i, c in enumerate(closes))
    poly = " ".join(f"{i*step:.1f},{h}" for i in range(len(closes)))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" fill="#0d1117" rx="4"/><polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5"/><polygon points="0,{h} {poly} {w},{h}" fill="{color}" opacity="0.1"/></svg>'


def build_kline_json(cached: list[dict], symbol: str) -> dict:
    """构建 K 线 OHLCV JSON"""
    bars = []
    for r in cached[-60:]:
        bars.append({
            "time": r.get("timestamp", "")[:10],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(float(r["volume"])),
        })
    return {"symbol": symbol, "bars": bars, "count": len(bars)}

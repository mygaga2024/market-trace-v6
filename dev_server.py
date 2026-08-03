#!/usr/bin/env python3
"""
Market Trace V6.0 — 独立前端开发服务器

零依赖后端逻辑：不需要 Redis、数据库、Agent。
即时启动，所有 API 返回 mock 数据，前端所有按钮/Tab/弹窗可交互验证。

用法:
    python3 dev_server.py
    → 打开 http://localhost:19378
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
TEMPLATE_PATH = ROOT / "templates" / "dashboard.html"
STATIC_DIR = ROOT / "static"

MOCK_STOCKS = [
    {"symbol": "000001", "name": "平安银行", "price": 12.56, "change_pct": 2.34},
    {"symbol": "000002", "name": "万科A", "price": 15.20, "change_pct": -1.02},
    {"symbol": "000333", "name": "美的集团", "price": 58.30, "change_pct": 0.78},
    {"symbol": "000651", "name": "格力电器", "price": 42.15, "change_pct": 1.55},
    {"symbol": "000858", "name": "五粮液", "price": 168.50, "change_pct": -0.45},
    {"symbol": "600036", "name": "招商银行", "price": 38.72, "change_pct": 0.12},
    {"symbol": "600519", "name": "贵州茅台", "price": 1780.00, "change_pct": 3.21},
    {"symbol": "601318", "name": "中国平安", "price": 45.80, "change_pct": -1.85},
]

START_TIME = datetime.now(timezone.utc)


def json_response(data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return status, "application/json", body


def make_route(path: str, method: str = "GET") -> str:
    return f"{method}:{path.rstrip('/')}"


# ── Mock API handlers ──


def handle_health():
    uptime = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    return json_response({
        "status": "ok", "version": "1.3.0", "uptime_seconds": round(uptime, 1),
    })


def handle_health_detail():
    uptime = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    return json_response({
        "status": "ok", "version": "1.3.0", "uptime_seconds": round(uptime, 1),
        "redis": "connected", "database": "connected",
        "agents": {"macro": True, "signal": True, "trace": True, "risk": True, "chief": True},
        "llm_chain": {
            "primary": {"api_key_configured": True, "provider": "deepseek", "model": "deepseek-chat"},
            "secondary": {"api_key_configured": True, "provider": "deepseek", "model": "deepseek-reasoner"},
            "tertiary": {"api_key_configured": True, "provider": "gemini", "model": "gemini-2.5-pro"},
            "quaternary": {"api_key_configured": True, "provider": "gemini", "model": "gemini-2.5-pro"},
            "quinary": {"api_key_configured": True, "provider": "zhipu", "model": "glm-4-flash"},
            "senary": {"api_key_configured": True, "provider": "siliconflow", "model": "THUDM/GLM-Z1-9B-0414"},
            "septenary": {"api_key_configured": True, "provider": "qianfan", "model": "ernie-speed-pro-128k"},
        },
        "agents_running": 5,
    })


def handle_status():
    uptime = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    return json_response({
        "version": "1.3.0", "uptime_seconds": round(uptime, 1),
        "decision_stats": {"total": 42, "buy": 15, "sell": 8, "hold": 19},
        "case_stats": {"total": 128, "avg_outcome": 0.023, "win_rate": 0.62},
        "latest_decision": {
            "action": "BUY", "confidence": 0.78,
            "reasoning": "RAI 指数偏高，市场做多情绪浓厚，技术指标金叉确认，建议小幅建仓。",
            "provider": "deepseek",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })


def handle_reports(agent, is_latest=False):
    items = [
        {"report_id": f"r-{agent}-001", "agent": agent, "symbol": "000001",
         "summary": f"{agent} 分析报告测试数据", "confidence": 0.75,
         "status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(),
         "data": {"risk_appetite_index": 0.62, "interpretation": {"regime": "震荡偏多", "sentiment": "neutral"}}},
    ] if agent == "macro" else [
        {"report_id": f"r-{agent}-001", "agent": agent, "symbol": "000001",
         "summary": f"{agent} 分析报告测试数据", "confidence": 0.7,
         "status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(),
         "data": {}},
    ]

    if is_latest:
        item = items[0]
        item.pop("report_id")
        return json_response(item)
    return json_response({"agent": agent, "count": len(items), "items": items})


def handle_analyze(symbol):
    stock = next((s for s in MOCK_STOCKS if s["symbol"] == symbol), None)
    if not stock:
        return json_response({"error": f"股票 {symbol} 数据不足"}, 400)

    return json_response({
        "symbol": symbol,
        "name": stock["name"],
        "price": stock["price"],
        "change_pct": stock["change_pct"],
        "trend": "bullish" if stock["change_pct"] > 0 else "bearish",
        "indicators": {
            "ma5": round(stock["price"] * 0.99, 2),
            "ma10": round(stock["price"] * 0.97, 2),
            "ma20": round(stock["price"] * 0.95, 2),
            "ma60": round(stock["price"] * 0.85, 2),
            "macd": {"dif": 0.35, "dea": 0.28, "histogram": 0.14},
            "bollinger": {"upper": round(stock["price"]*1.05,2), "middle": stock["price"], "lower": round(stock["price"]*0.95,2), "bandwidth": 0.1},
            "kdj": {"k": 58.2, "d": 52.1, "j": 70.4},
            "rsi": 58.5,
            "vol_ratio": 1.25,
            "atr": 0.35,
            "support_resistance": {"support": round(stock["price"]*0.92,2), "resistance": round(stock["price"]*1.08,2), "pivot": stock["price"]},
        },
        "trace_signals": [
            {"type": "VOLUME_SPIKE", "direction": "bullish", "strength": 0.6},
            {"type": "MACD_GOLDEN_CROSS", "direction": "bullish", "strength": 0.5},
        ],
        "strategy_hits": [
            {"type": "BUY", "label": "MACD金叉"},
            {"type": "BUY", "label": "放量突破"},
        ],
        "macro_rai": 0.62,
        "decision": {
            "action": "BUY",
            "confidence": 0.78,
            "reasoning": "RAI 指数偏高，市场做多情绪浓厚。技术面 MACD 金叉 + RSI 中性偏多，量价配合良好。建议轻仓试多。",
            "provider": "deepseek:deepseek-chat",
            "provider_status": "healthy",
        },
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "akshare",
    })


def handle_screen(strategy):
    names = {"breakout": "强势突破", "oversold": "超跌反弹", "strength": "主力介入", "risk": "风险预警"}
    return json_response({
        "strategy": names.get(strategy, strategy),
        "matched": 3,
        "results": [
            {**s, "vol_ratio": round(random.uniform(1.1, 3.5), 2)}
            for s in random.sample(MOCK_STOCKS, min(3, len(MOCK_STOCKS)))
        ],
    })


def handle_kline(symbol):
    base = next((s["price"] for s in MOCK_STOCKS if s["symbol"] == symbol), 10.0)
    import random as rnd
    bars = []
    price = base * 0.85
    for i in range(60):
        dt = datetime(2026, 6, 1) + __import__("datetime").timedelta(days=i)
        day_str = dt.strftime("%Y-%m-%d")
        o = price
        c = price * (1 + rnd.uniform(-0.03, 0.03))
        h = max(o, c) * (1 + rnd.uniform(0, 0.02))
        l = min(o, c) * (1 - rnd.uniform(0, 0.02))
        v = int(rnd.uniform(5000000, 50000000))
        bars.append({"time": day_str, "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2), "volume": v})
        price = c
    bars[-1]["close"] = base
    return json_response({"symbol": symbol, "bars": bars, "count": len(bars)})


def handle_risk_status():
    return json_response({
        "level": "normal", "daily_overrides": 3, "total_overrides": 12,
        "last_override_time": datetime.now(timezone.utc).isoformat(),
        "last_critical_time": "",
        "current_circuit_breaker": "none",
        "adaptive_suggestion": "",
    })


def handle_risk_overrides():
    return json_response({
        "count": 3, "overrides": [
            {"severity": "warning", "reason": "宏观极度悲观 vs 资金大幅流入", "symbol": "000001",
             "action": "REDUCE_CONFIDENCE", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"severity": "critical", "reason": "强势顶背离，强制平仓", "symbol": "600519",
             "action": "FORCE_SELL", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"severity": "warning", "reason": "宏观过度乐观 vs 资金大幅流出", "symbol": "000333",
             "action": "REDUCE_CONFIDENCE", "timestamp": datetime.now(timezone.utc).isoformat()},
        ],
    })


def handle_risk_position(symbol):
    return json_response({
        "symbol": symbol, "risk_level": "normal", "risk_multiplier": 1.0,
        "position_shares": 300, "suggested_amount": 30000, "method": "kelly",
        "capital": 100000, "win_prob": 0.5, "avg_win": 0.03, "avg_loss": 0.02,
    })


def handle_decisions():
    items = [
        {"decision_id": "dec-001", "action": "BUY", "confidence": 0.78,
         "reasoning": "RAI 高 + MACD 金叉，建议买入", "evidence_sources": ["macro", "signal"],
         "provider_label": "deepseek", "provider_status": "healthy",
         "timestamp": datetime.now(timezone.utc).isoformat()},
        {"decision_id": "dec-002", "action": "HOLD", "confidence": 0.55,
         "reasoning": "信号不明确，建议观望", "evidence_sources": ["trace"],
         "provider_label": "gemini", "provider_status": "healthy",
         "timestamp": datetime.now(timezone.utc).isoformat()},
        {"decision_id": "dec-003", "action": "SELL", "confidence": 0.82,
         "reasoning": "顶背离 + 放量下跌，建议止损", "evidence_sources": ["signal", "risk"],
         "risk_override": {"rule": "BEARISH_DIVERGENCE", "level": "critical"},
         "provider_label": "deepseek", "provider_status": "healthy",
         "timestamp": datetime.now(timezone.utc).isoformat()},
    ]
    return json_response({"count": len(items), "stats": {"buy": 1, "sell": 1, "hold": 1}, "items": items})


def handle_decision_detail(decision_id):
    return json_response({
        "decision_id": decision_id, "action": "BUY", "confidence": 0.78,
        "reasoning": "RAI 指数偏高，市场做多情绪浓厚。技术面 MACD 金叉 + RSI 中性偏多，量价配合良好。建议轻仓试多，止损设在 MA20 下方。",
        "evidence_sources": [
            "宏观分析: RAI=0.62, 震荡偏多",
            "信号分析: MACD金叉, RSI=58.5",
            "资金分析: VOLUME_SPIKE bullish, 量比 1.25x",
        ],
        "evidence_chain": [
            "MacroAgent → 宏观经济数据 → RAI=0.62 → 偏多",
            "SignalAgent → K线技术指标 → MACD金叉 → 买入信号",
            "TraceAgent → 资金流量 → 主力净流入 → 跟进",
            "ChiefAnalyst → 综合决策 → BUY confidence=0.78",
        ],
        "risk_override": None,
        "provider_label": "deepseek", "provider_status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def handle_backtest_summary():
    results = {}
    for stock in MOCK_STOCKS[:3]:
        results[stock["symbol"]] = {
            "breakout": {"sharpe": 1.45, "max_drawdown_pct": 8.5, "win_rate_pct": 62.0, "profit_factor": 2.1, "score": 3.2},
            "oversold": {"sharpe": 0.92, "max_drawdown_pct": 12.0, "win_rate_pct": 55.0, "profit_factor": 1.6, "score": 2.1},
            "strength": {"sharpe": 1.12, "max_drawdown_pct": 9.8, "win_rate_pct": 58.0, "profit_factor": 1.8, "score": 2.8},
        }
    return json_response({"count": len(results), "results": results})


def handle_backtest_strategies():
    return json_response({"strategies": {
        "breakout": {"status": "active", "consecutive_losses": 0, "last_score": 1.45},
        "oversold": {"status": "active", "consecutive_losses": 2, "last_score": 0.92},
        "strength": {"status": "active", "consecutive_losses": 0, "last_score": 1.12},
        "risk": {"status": "active", "consecutive_losses": 1, "last_score": 0.78},
        "ma_golden_cross": {"status": "disabled", "consecutive_losses": 5, "last_score": -0.35},
        "volume_breakout": {"status": "active", "consecutive_losses": 0, "last_score": 1.05},
        "rsi_reversal": {"status": "active", "consecutive_losses": 3, "last_score": 0.55},
    }})


def handle_backtest_run():
    return json_response({"count": 8, "results": {}, "strategy_changes": {}})


def handle_backtest_enable(name):
    return json_response({"strategy": name, "status": "active"})

def handle_backtest_rolling(symbol):
    return json_response({
        "symbol": symbol, "strategy": "breakout", "label": "强势突破",
        "train_bars": 70, "test_bars": 30, "total_windows": 5, "active_windows": 3,
        "best_params": {"lookback": 20, "vol_mult": 1.5},
        "avg_win_rate": 55.2, "avg_sharpe": 1.23, "avg_return": 12.5,
        "min_return": -5.2, "max_return": 28.9, "consistency": 0.6,
        "windows": [],
    })


# mock watchlist state
_mock_watchlist: list[dict] = [
    {"symbol": "000001", "name": "平安银行", "notes": "", "added_at": datetime.now(timezone.utc).isoformat(),
     "price": 12.56, "change_pct": 2.34},
    {"symbol": "600519", "name": "贵州茅台", "notes": "长线持有", "added_at": datetime.now(timezone.utc).isoformat(),
     "price": 1780.00, "change_pct": 3.21},
]


def handle_watchlist_get():
    return json_response({"count": len(_mock_watchlist), "items": _mock_watchlist})


def handle_watchlist_post(body: dict):
    sym = body.get("symbol", "").strip()
    if not sym:
        return json_response({"error": "请提供股票代码"}, 400)
    for item in _mock_watchlist:
        if item["symbol"] == sym:
            return json_response(item)
    stock = next((s for s in MOCK_STOCKS if s["symbol"] == sym), None)
    entry = {
        "symbol": sym, "name": stock["name"] if stock else sym,
        "notes": body.get("notes", ""),
        "added_at": datetime.now(timezone.utc).isoformat(),
        "price": stock["price"] if stock else None,
        "change_pct": stock["change_pct"] if stock else None,
    }
    _mock_watchlist.append(entry)
    return json_response(entry)


def handle_watchlist_delete(symbol: str):
    global _mock_watchlist
    before = len(_mock_watchlist)
    _mock_watchlist = [i for i in _mock_watchlist if i["symbol"] != symbol]
    if len(_mock_watchlist) == before:
        return json_response({"error": f"股票 {symbol} 不在持仓列表中"}, 404)
    return json_response({"symbol": symbol, "removed": True})


def handle_logs():
    """返回 mock 系统日志"""
    mock_lines = [
        "10:00:00 | INFO     | Market Trace V6.0 正在启动...",
        "10:00:01 | INFO     | Redis 已连接",
        "10:00:01 | INFO     | 数据库已初始化",
        "10:00:02 | INFO     | LLM 回退链已就绪: DS Chat → DS Reasoner → Gemini K1 → Gemini K2 → GLM Flash → 硅基流动 → 千帆 → 纯规则",
        "10:00:03 | INFO     | 5 个 Agent 已启动",
        "10:00:05 | INFO     | 并发预加载 热门 20 只 (并发度=5)…",
        "10:00:15 | INFO     | 预加载 000001: 60 条K线",
        "10:00:30 | INFO     | 热门预加载完成: 18/20 只 (25.0s)",
    ]
    return json_response({"file": "market_trace_dev.log", "count": len(mock_lines), "lines": mock_lines})


def handle_market_index():
    """返回 mock 大盘指数数据"""
    return json_response({
        "indices": [
            {"code": "sh000001", "name": "上证指数", "close": 3350.68, "change": 14.02, "涨跌幅": 0.42, "volume": 285000000, "amount": 320000000000},
            {"code": "sz399001", "name": "深证成指", "close": 10823.45, "change": -22.80, "涨跌幅": -0.21, "volume": 420000000, "amount": 480000000000},
            {"code": "sz399006", "name": "创业板指", "close": 2215.80, "change": 25.20, "涨跌幅": 1.15, "volume": 180000000, "amount": 195000000000},
            {"code": "sh000688", "name": "科创50", "close": 985.30, "change": 8.50, "涨跌幅": 0.87, "volume": 85000000, "amount": 72000000000},
            {"code": "sh000300", "name": "沪深300", "close": 3980.55, "change": 5.97, "涨跌幅": 0.15, "volume": 350000000, "amount": 280000000000},
        ],
        "breadth": {"up": 2156, "down": 2834, "flat": 136},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "akshare:sina",
    })


def handle_paper_account():
    """返回 mock 纸上交易账户"""
    return json_response({
        "account_id": "default",
        "initial_capital": 100000, "capital": 95680.50, "total_equity": 102430.20,
        "total_pnl": 2430.20, "total_pnl_pct": 2.43, "position_count": 2,
        "total_orders": 5,
        "positions": [
            {"symbol": "000001", "quantity": 300, "avg_cost": 11.23, "cost_basis": 3369, "entry_time": "2026-06-10T09:30:00"},
            {"symbol": "600519", "quantity": 100, "avg_cost": 1785.50, "cost_basis": 178550, "entry_time": "2026-06-09T14:00:00"},
        ],
        "recent_orders": [
            {"order_id": "o1", "symbol": "000001", "action": "BUY", "quantity": 300, "price": 11.23, "reason": "AI诊股: 强势突破信号", "timestamp": "2026-06-10T09:30:00"},
            {"order_id": "o2", "symbol": "600519", "action": "BUY", "quantity": 100, "price": 1785.50, "reason": "AI诊股: 超跌反弹", "timestamp": "2026-06-09T14:00:00"},
        ],
    })


def handle_smart_scan(strategy: str):
    """返回 mock 智能综合扫描结果"""
    labels = {"breakout": "强势突破", "oversold": "超跌反弹", "strength": "主力介入",
              "risk": "风险预警", "ma_golden_cross": "均线金叉", "volume_breakout": "放量突破", "rsi_reversal": "RSI反转"}
    return json_response({
        "total": 5526, "scored": 5, "elapsed_seconds": 8.3,
        "results": [
            {"symbol": "000001", "name": "平安银行", "price": 12.56, "change_pct": 2.34, "strategy": "breakout", "strategy_label": "强势突破", "score": 8.5},
            {"symbol": "600519", "name": "贵州茅台", "price": 1780.00, "change_pct": 3.21, "strategy": "strength", "strategy_label": "主力介入", "score": 7.8},
            {"symbol": "000858", "name": "五粮液", "price": 156.80, "change_pct": -1.02, "strategy": "oversold", "strategy_label": "超跌反弹", "score": 6.2},
        ],
    })


def handle_full_scan(strategy: str):
    """返回 mock 全市场扫描结果"""
    labels = {"breakout": "强势突破", "oversold": "超跌反弹", "strength": "主力介入",
              "risk": "风险预警", "ma_golden_cross": "均线金叉", "volume_breakout": "放量突破", "rsi_reversal": "RSI反转"}
    return json_response({
        "strategy": labels.get(strategy, strategy), "strategy_id": strategy,
        "total_stocks": 5526, "checked": 5526, "too_few_data": 200, "errors": 5,
        "matched": 5, "elapsed_seconds": 6.5,
        "results": [
            {"symbol": "000001", "name": "平安银行", "price": 12.56, "change_pct": 2.34, "vol_ratio": 2.5},
            {"symbol": "600519", "name": "贵州茅台", "price": 1780.00, "change_pct": 3.21, "vol_ratio": 1.8},
            {"symbol": "000858", "name": "五粮液", "price": 156.80, "change_pct": -1.02, "vol_ratio": 3.1},
        ],
    })


# ── Route table ──

ROUTES = {
    "GET:/health": handle_health,
    "GET:/health/detail": handle_health_detail,
    "GET:/status": handle_status,
    "GET:/api/market/index": handle_market_index,
    "GET:/reports/macro/latest": lambda: handle_reports("macro", is_latest=True),
    "GET:/reports/signal/latest": lambda: handle_reports("signal", is_latest=True),
    "GET:/reports/trace/latest": lambda: handle_reports("trace", is_latest=True),
    "GET:/decisions": handle_decisions,
    "GET:/risk/status": handle_risk_status,
    "GET:/risk/overrides": handle_risk_overrides,
    "GET:/backtest/summary": handle_backtest_summary,
    "GET:/backtest/strategies": handle_backtest_strategies,
    "POST:/backtest/run": handle_backtest_run,
    "GET:/watchlist": handle_watchlist_get,
}

# regex-based routes
import re
REGEX_ROUTES = [
    (re.compile(r"^/reports/(macro|signal|trace)\?limit=5$"), "GET",
     lambda m: handle_reports(m.group(1), is_latest=False)),
    (re.compile(r"^/analyze/(.+)$"), "POST",
     lambda m: handle_analyze(m.group(1))),
    (re.compile(r"^/screen/(.+)$"), "POST",
     lambda m: handle_screen(m.group(1))),
    (re.compile(r"^/api/kline/(.+)$"), "GET",
     lambda m: handle_kline(m.group(1))),
    (re.compile(r"^/risk/position/(.+)$"), "GET",
     lambda m: handle_risk_position(m.group(1))),
    (re.compile(r"^/decisions/(.+)$"), "GET",
     lambda m: handle_decision_detail(m.group(1))),
    (re.compile(r"^/backtest/strategies/(.+)/enable$"), "POST",
      lambda m: handle_backtest_enable(m.group(1))),
    (re.compile(r"^/backtest/rolling/(.+)$"), "GET",
      lambda m: handle_backtest_rolling(m.group(1))),
    (re.compile(r"^/watchlist$"), "POST",
     lambda _: None),  # handled via body parsing below
    (re.compile(r"^/watchlist/(.+)$"), "DELETE",
     lambda m: handle_watchlist_delete(m.group(1))),
     (re.compile(r"^/scan/(smart|breakout|oversold|strength|risk|ma_golden_cross|volume_breakout|rsi_reversal)$"), "POST",
      lambda m: handle_smart_scan(m.group(1)) if m.group(1) == "smart" else handle_full_scan(m.group(1))),
]

# prefix-based static routes for reports with query params
REPORT_ROUTES = {
    "/reports/macro": lambda: handle_reports("macro", is_latest=False),
    "/reports/signal": lambda: handle_reports("signal", is_latest=False),
    "/reports/trace": lambda: handle_reports("trace", is_latest=False),
    "/logs": lambda: handle_logs(),
    "/paper/account": lambda: handle_paper_account(),
}


class DevHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{self.command}] {args[0]}")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _serve_api(self, method: str):
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        full_path = path
        if query:
            full_path += "?" + query

        # Exact match
        route_key = f"{method}:{path.rstrip('/')}"
        if route_key in ROUTES:
            handler = ROUTES[route_key]
        else:
            # Regex match
            handler = None
            for pattern, http_method, h in REGEX_ROUTES:
                if http_method != method:
                    continue
                m = pattern.match(path)
                if m:
                    if http_method == "POST" and pattern.pattern == r"^/watchlist$":
                        body_len = int(self.headers.get("Content-Length", 0))
                        body_raw = self.rfile.read(body_len) if body_len else b"{}"
                        try:
                            body = json.loads(body_raw)
                        except Exception:
                            body = {}
                        handler = lambda: handle_watchlist_post(body)
                    else:
                        handler = lambda m=m: h(m)
                    break

        # Prefix check for report routes
        if handler is None:
            for prefix, h in REPORT_ROUTES.items():
                if path == prefix or path.startswith(prefix + "?"):
                    handler = h
                    break

        if handler is None:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())
            return

        try:
            status, content_type, body = handler()
        except Exception as e:
            status, content_type, body = 500, "application/json", json.dumps({"error": str(e)}).encode()

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/dashboard":
            if not TEMPLATE_PATH.exists():
                self.send_error(500, "template not found")
                return
            html = TEMPLATE_PATH.read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif path.startswith("/static/"):
            # 路径规范化，防止 /static/../env 等路径遍历读取任意文件
            static_root = STATIC_DIR.resolve()
            try:
                file_path = (STATIC_DIR / path[len("/static/"):]).resolve().relative_to(static_root)
            except ValueError:
                self.send_error(403, "Forbidden")
                return
            file_path = static_root / file_path
            self.send_response(200)
            if file_path.suffix == ".js":
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
            elif file_path.suffix == ".css":
                self.send_header("Content-Type", "text/css; charset=utf-8")
            elif file_path.suffix == ".svg":
                self.send_header("Content-Type", "image/svg+xml")
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            try:
                self.wfile.write(file_path.read_bytes())
            except FileNotFoundError:
                self.send_error(404)
        else:
            self._serve_api("GET")

    def do_POST(self):
        self._serve_api("POST")

    def do_DELETE(self):
        self._serve_api("DELETE")


def main():
    port = 19378
    # 切换到项目根目录（SimpleHTTPRequestHandler 以此为基础）
    os.chdir(str(ROOT))

    server = HTTPServer(("0.0.0.0", port), DevHandler)
    print(f"""
  Market Trace V6.0 — 前端开发服务器
  ─────────────────────────────────────
  Dashboard:  http://localhost:{port}
  静态文件:   /static/
  Mock API:  所有 /health /status /analyze ... 都返回假数据
  无需 Redis / 数据库 / Agent
  
  按 Ctrl+C 停止
  """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.shutdown()


if __name__ == "__main__":
    main()

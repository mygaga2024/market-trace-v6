"""
Market Trace V6.0 — 前端 WebUI 结构验证测试

验证项:
- Dashboard HTML 返回 200 + 关键元素存在
- 静态文件 (JS/CSS) 可访问且非空
- JS 语法正确 (通过 node --check)
- CSS 包含必要类名

用法:
    python3 -m pytest tests/test_webui.py -q      # 仅前端测试
    python3 -m pytest tests/ -q                   # 全量测试
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────
# HTML 结构验证
# ─────────────────────────────────────────────

def _load_html() -> str:
    template = ROOT / "templates" / "dashboard.html"
    assert template.exists(), f"模板不存在: {template}"
    return template.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return _load_html()


def test_html_not_empty(html):
    """Dashboard HTML 不为空"""
    assert len(html) > 1000, f"HTML 过短: {len(html)} bytes"


def test_html_contains_core_elements(html):
    """HTML 包含所有核心 UI 元素"""
    required = [
        # 搜索与诊股
        "stock-input", "analyze-btn", "analyze-result",
        # 网格卡片
        "rai-value", "agent-count", "llm-chain",
        # 决策区
        "decision-area", "decision-action",
        # Tab 栏
        'data-tab="health"', 'data-tab="status"', 'data-tab="reports"',
        'data-tab="signal"', 'data-tab="trace"', 'data-tab="decisions"',
        'data-tab="risk-history"', 'data-tab="backtest"',
        # 选股策略按钮
        'screenStocks(', "强势突破", "超跌反弹", "主力介入", "风险预警",
        # 风控卡片 (上次优化)
        "risk-card", "risk-level-display", "risk-override-count",
        # 决策弹窗 (上次优化)
        "decision-modal", "decision-modal-body",
        # 持仓列表 (本次优化)
        "watchlist-input", "watchlist-add-btn", "watchlist-items",
        # K 线图
        "kline-chart",
        # 尾部
        "dashboard.js", "charts.js", "dashboard.css",
    ]
    for elem in required:
        assert elem in html, f"HTML 缺少元素: {elem}"


def test_html_contains_chinese_labels(html):
    """HTML 包含关键中文标签"""
    labels = ["持仓列表", "诊股", "风控闭环", "风控历史", "策略回测", "健康检查", "决策历史"]
    for label in labels:
        assert label in html, f"HTML 缺少标签: {label}"


def test_html_script_order(html):
    """charts.js 在 dashboard.js 之前加载 (依赖关系)"""
    charts_idx = html.index("charts.js")
    dash_idx = html.index("dashboard.js")
    assert charts_idx < dash_idx, "charts.js 必须在 dashboard.js 之前加载"


# ─────────────────────────────────────────────
# 静态文件验证
# ─────────────────────────────────────────────

STATIC_FILES = [
    ("static/js/dashboard.js", "application/javascript"),
    ("static/js/charts.js", "application/javascript"),
    ("static/css/dashboard.css", "text/css"),
    ("static/favicon.svg", "image"),
    ("static/manifest.json", "application/json"),
]


@pytest.mark.parametrize("filepath,content_type", STATIC_FILES)
def test_static_file_exists(filepath, content_type):
    """静态文件存在且非空"""
    full = ROOT / filepath
    assert full.exists(), f"文件不存在: {filepath}"
    content = full.read_bytes()
    assert len(content) > 0, f"文件为空: {filepath}"


# ─────────────────────────────────────────────
# JS 语法检查
# ─────────────────────────────────────────────

def test_dashboard_js_syntax():
    """dashboard.js 通过 Node.js 语法检查"""
    result = subprocess.run(
        ["node", "--check", str(ROOT / "static/js/dashboard.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"dashboard.js 语法错误:\n{result.stderr}"


def test_charts_js_syntax():
    """charts.js 通过 Node.js 语法检查"""
    result = subprocess.run(
        ["node", "--check", str(ROOT / "static/js/charts.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"charts.js 语法错误:\n{result.stderr}"


# ─────────────────────────────────────────────
# JS 引用完整性检查 (所有 $id引用 的 ID 存在于 HTML)
# ─────────────────────────────────────────────

def test_js_id_references_exist_in_html(html):
    """dashboard.js 中 $id('...') 引用的所有 ID 都存在于 HTML 中"""
    js_content = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    import re
    ids_in_js = set(re.findall(r"\$id\('([^']+)'\)", js_content))
    ids_in_js.update(re.findall(r'\$id\("([^"]+)"\)', js_content))
    ids_in_js.update(re.findall(r'getElementById\("([^"]+)"\)', js_content))

    for elem_id in sorted(ids_in_js):
        assert f'id="{elem_id}"' in html or f"id='{elem_id}'" in html, \
            f"JS 引用了 {elem_id} 但 HTML 中不存在"


# ─────────────────────────────────────────────
# CSS 必要类名检查
# ─────────────────────────────────────────────

def test_css_contains_required_classes():
    """dashboard.css 包含上一次优化新增的所有类名"""
    css = (ROOT / "static/css/dashboard.css").read_text(encoding="utf-8")
    required = [
        # 风控
        ".risk-card", ".risk-indicator", ".risk-normal", ".risk-elevated", ".risk-critical",
        # Modal
        ".modal-overlay", ".modal-content", ".modal-header", ".modal-close", ".modal-body",
        ".modal-section", ".modal-label", ".modal-value", ".modal-chain-item",
        # 策略管理
        ".strat-mgmt", ".strat-mgmt-header", ".toggle-btn", ".toggle-btn-enable",
        # 仓位建议
        ".position-box", ".pos-level",
        # Toast
        ".toast-success",
        # 决策行
        ".decision-row",
    ]
    for cls_name in required:
        assert cls_name in css, f"CSS 缺少类名: {cls_name}"


# ─────────────────────────────────────────────
# dev_server.py 存在性检查
# ─────────────────────────────────────────────

def test_dev_server_exists():
    """dev_server.py 存在且可执行"""
    dev_server = ROOT / "dev_server.py"
    assert dev_server.exists(), "dev_server.py 不存在"
    content = dev_server.read_text(encoding="utf-8")
    assert "DevHandler" in content or "SimpleHTTPRequestHandler" in content
    assert "def main" in content


# ─────────────────────────────────────────────
# API 端点与前端一致性 (前端调用的所有端点都有 mock)
# ─────────────────────────────────────────────

def test_dev_server_mocks_all_endpoints():
    """dev_server.py 为所有前端 fetch 调用提供了 mock"""
    js_content = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    dev_content = (ROOT / "dev_server.py").read_text(encoding="utf-8")

    import re
    endpoints = set(re.findall(r"fetchAuth\('([^']+)", js_content))
    # 去掉动态参数
    stripped = set()
    for ep in endpoints:
        base = ep.split("?")[0]
        if base.startswith("/analyze/"):
            stripped.add("/analyze/")
        elif base.startswith("/screen/"):
            stripped.add("/screen/")
        elif base.startswith("/api/kline/"):
            stripped.add("/api/kline/")
        elif base.startswith("/risk/position/"):
            stripped.add("/risk/position/")
        elif base.startswith("/decisions/"):
            stripped.add("/decisions/")
        elif base.startswith("/backtest/strategies/"):
            stripped.add("/backtest/strategies/")
        elif base.startswith("/watchlist/"):
            stripped.add("/watchlist/")
        else:
            stripped.add(base)

    for ep in sorted(stripped):
        assert ep in dev_content, f"dev_server.py 缺少端点 mock: {ep}"

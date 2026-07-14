# Task 6: 前端 JS 拆分

## Status: done

## Goal
将 1505 行的单文件 `dashboard.js` 按 Tab 功能拆分为独立模块，提高可维护性。保持现有功能不变。

## Files
- `static/js/dashboard.js` — 缩减为入口 + 工具函数 + 轮询
- `static/js/tab-analyze.js` — **新文件**。诊股/选股/smart scan 逻辑
- `static/js/tab-backtest.js` — **新文件**。回测/策略管理逻辑
- `static/js/tab-risk.js` — **新文件**。风控状态/历史/仓位逻辑
- `static/js/tab-watchlist.js` — **新文件**。持仓列表逻辑
- `static/js/tab-reports.js` — **新文件**。报告/决策历史/日志逻辑
- `templates/dashboard.html` — 添加新 JS 文件的 `<script>` 标签

## Steps
1. 创建 `static/js/tab-analyze.js`，迁移诊股/选股/smart scan 相关函数
2. 创建 `static/js/tab-backtest.js`，迁移回测相关函数
3. 创建 `static/js/tab-risk.js`，迁移风控相关函数
4. 创建 `static/js/tab-watchlist.js`，迁移持仓相关函数
5. 创建 `static/js/tab-reports.js`，迁移报告/决策/日志相关函数
6. 缩减 `dashboard.js` 为 IIFE 入口 + 工具函数 + 轮询/初始化
7. `templates/dashboard.html` 按顺序加载新 JS 文件
8. 本地 `python3 dev_server.py` 启动 + 浏览器验证所有 Tab 功能正常
9. 运行 `python3 -m pytest tests/test_webui.py -v`

## Done When
- [ ] dashboard.js 从 1505 行缩减到 <300 行
- [ ] 5 个新模块文件各自 <300 行
- [ ] 所有 Tab 功能正常（dev_server 验证）
- [ ] `pytest tests/test_webui.py -v` 全通过
- [ ] NAS 部署后 Web 页面功能正常

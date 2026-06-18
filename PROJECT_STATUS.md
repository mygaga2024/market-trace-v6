# PROJECT_STATUS — Market Trace V6

## 版本

**1.1.8**

## 已知问题

<!-- 暂无已知严重 bug -->
<!-- 发现新问题时在此追加，格式: YYYY-MM-DD | 问题描述 | 临时方案 -->

## 最近修复

| 日期 | Commit | 修复内容 |
|------|--------|---------|
| 2025-06-18 | `c5731da` | 添加 AGENTS.md，规范 AI 会话启动/结束流程 |
| 2025-06-18 | `fbce5cd` | 移除 minimax 收费大模型 senary，保留小模型 quinary |
| 2025-06-17 | `724d8f8` | Claude Opus 审查收尾：TTL延长/KDJ递推平滑/测试清理/dockerignore |
| 2025-06-17 | `d4056fe` | 15项代码审查修复 |
| 2025-06-17 | `7e06786` | Tab 切换后自动滚动 + 卡片点击跳转到对应 Tab |
| 2025-06-17 | `7dec35e` | 持仓列表改为新浪实时价格优先，K线缓存降级兜底 |
| 2025-06-17 | `28289ef` | 帮助 Tab 缺失 fetcher 导致无法显示 |
| 2025-06-16 | `b46ef94` | WebUI 新增帮助 Tab，系统使用指南 |
| 2025-06-16 | `fd0dac0` | 路由顺序修正 + Smart Scan 增加 checked 追踪 |
| 2025-06-16 | `3fcf74d` | 全市场扫描用 Sina 批量补全实时价格 |

## LLM Fallback Chain

```
primary    → deepseek-chat
secondary  → deepseek-reasoner
tertiary   → gemini-2.5-pro
quaternary → gemini-2.5-pro (备胎)
quinary    → abab6.5s-chat (免费)
septenary  → glm-4-flash (免费)
octonary   → glm-4-plus
fallback   → 纯规则
```

## 部署

- 端口: `19377`
- 容器名: `mt6-app` (docker-compose)
- 数据源: AkShare + Tushare (开发默认)

## 测试

```bash
pytest tests/ -v
```

# PROJECT_STATUS — Market Trace V6

## 版本

**1.1.8**

## 已知问题

<!-- 暂无已知严重 bug -->
<!-- 发现新问题时在此追加，格式: YYYY-MM-DD | 问题描述 | 临时方案 -->

## 最近修复

| 日期 | Commit | 修复内容 |
|------|--------|---------|
| 2026-06-22 | `c0b0bcc` | 策略灵敏度调整：7策略阈值放宽 + 趋势ma60回退 + NAS实测BUY/SELL正确返回 |
| 2026-06-22 | `12556e2` | 修复诊股永远HOLD：数据契约断裂(缺direction/strength) → LLM+规则双崩溃 → 降到兜底HOLD |
| 2026-06-22 | `7e74cf0`, `a8c4500` | AGENTS.md 强化收尾自检机制(8项清单) + WebUI 28项优化 + dev_server数据对齐 |
| 2026-06-18 | `f72903a` | 4项架构整改：共享决策引擎/双路径风控/多LLM共识/Agent结论注入 |
| 2026-06-18 | `f658607` | WebUI 帮助指南 LLM 回退链更新为七级 |
| 2026-06-18 | `085f3ff` | 统一版本号 1.1.8 + AGENTS.md NAS 部署步骤修正（tar+ssh） |
| 2026-06-18 | `7fdf883` | 修复 `_clean_json_content` 数组截断 bug（3处修复） |
| 2026-06-18 | `4221065` | 补充 `_clean_json_content` 专项测试（8个场景） |
| 2026-06-18 | — | 精简 LLM 回退链：5+1（移除 MiniMax/glm-4-plus 收费模型） |
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
primary    → deepseek-chat        (DeepSeek)
secondary  → deepseek-reasoner    (DeepSeek 推理)
tertiary   → gemini-2.5-pro       (Gemini Key1)
quaternary → gemini-2.5-pro       (Gemini Key2 备胎)
quinary    → glm-4-flash          (智谱免费)
senary     → THUDM/GLM-Z1-9B-0414  (硅基流动免费)
septenary  → ernie-speed-pro-128k    (百度千帆免费)
fallback   → RuleBasedAnalyzer    (纯规则)
```

已移除：abab6.5s-chat（MiniMax 无免费模型）、glm-4-plus（智谱收费）

## 部署

- 端口: `19377`
- 容器名: `mt6-app` (docker-compose)
- 数据源: AkShare + Tushare (开发默认)

## 测试

```bash
pytest tests/ -v
```

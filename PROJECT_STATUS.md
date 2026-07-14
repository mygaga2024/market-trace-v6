# PROJECT_STATUS — Market Trace V6

## 版本

**1.2.0**

## 已知问题

<!-- 暂无已知严重 bug -->
<!-- 发现新问题时在此追加，格式: YYYY-MM-DD | 问题描述 | 临时方案 -->

## 最近修复

| 日期 | Commit | 修复内容 |
|------|--------|---------|
| 2026-07-14 | * | 全模块评估+7项P1修复: 统一技术指标计算/Scanner并发优化/版本号1.2.0/prefetch迁移httpx/前端JS拆分/Scanner粗筛去重/dev_server补全backtest rolling mock |
| 2026-07-01 | `1893cd1` | 风控等级卡死修复: get_risk_state()增加_auto_heal自愈 + main.py小时级定时clear_daily_counters |
| 2026-07-01 | `e5af383` | 涨跌家数补充科创板(sh688xxx)+涨跌颜色按国内习惯(红涨绿跌) |
| 2026-06-25 | `09adc2f` | 代码审查修复7项: P1 _dummy_decision NameError / P3 ATR去重 / P4 asyncio规范 / P5 日志更新 / P7 API速率限制 / P8 env替换 / P10 httpx复用 + 42个新测试(237 total) |
| 2026-06-23 | `85b110d` | 恢复switchTab的scrollIntoView: tab-panel在页面底部, 去掉滚动导致内容加载但不可见 |
| 2026-06-23 | `5e33f33` | 健康检查/状态详情/系统日志/帮助4标签移至右上角诊股输入框上方工具栏 |
| 2026-06-23 | `7a86250` | 新增大盘指数+涨跌家数+全局时间北京时区修复+指数卡片5列丰富布局(代码/价格/涨跌额/涨跌幅/成交量) |
| 2026-06-22 | `d359ae2` | 纸上交易三连修: warning不强制WAIT + HOLD日志可见 + 高价股允许单股买入 + 文件持久化 |
| 2026-06-22 | `3daf967` | 决策动作+风控等级汉化: BUY→买入/SELL→卖出/HOLD→持仓观望/WAIT→等待/critical→危险 |
| 2026-06-22 | `e0193d8` | AGENTS.md 强化Web双实测规则: 前后端分离, 各自验证后再交付 |
| 2026-06-22 | `c0b0bcc` | 策略灵敏度调整：7策略阈值放宽, NAS实测BUY正确返回 |
| 2026-06-22 | `5a0b9eb` | 诊股趋势修复: ma60回退 + 策略检测异常日志 |
| 2026-06-22 | `51583fb`, `12556e2` | LLM降级崩溃诊断 + 修复诊股永远HOLD |
| 2026-06-22 | `7e74cf0`, `a8c4500` | AGENTS.md 强化收尾自检 + WebUI 28项优化 |
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

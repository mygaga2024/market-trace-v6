# PROJECT_STATUS — Market Trace V6

## 版本

**1.3.5**

## 已知问题

<!-- 暂无已知严重 bug -->
<!-- 发现新问题时在此追加，格式: YYYY-MM-DD | 问题描述 | 临时方案 -->

## 最近修复

| 日期 | Commit | 修复内容 |
|------|--------|---------|
| 2026-08-04 | — | RAI 卡片未对齐修复: 左栏 2 列 grid 中跨双列卡(大盘指数/持仓)造成 RAI 右侧空洞错位; 重排卡片 DOM 顺序(RAI+Agent 并排→大盘→持仓→AI决策链+风控) + grid-auto-flow:dense 防空洞; 版本 1.3.4→1.3.5 |
| 2026-08-04 | — | Web 结构重组: 大屏双栏仪表盘(左 400px 监控卡片 2 列+密集卡跨双列 / 右 数据面板) + 主 Tab 导航置顶 sticky(两套 tab 体系合并为 11 tab 带分组分隔线) + toolbar-links 移除 + 移动端单列/横向滚动; 原生 JS 零改动(id/事件全保留); 版本 1.3.3→1.3.4 |
| 2026-08-04 | — | Web UI 视觉重构: 深空蓝黑金融终端风 — 背景径向渐变+顶部品牌光带+卡片内高光/悬浮光晕+tab 渐变高亮+表格/按钮/滚动条/模态/扫描区系统性打磨; 纯 CSS 强化(类名全保留) + scan-section 容器; 版本 1.3.2→1.3.3 |
| 2026-08-04 | — | Web 登录/登出入口: header 工具栏新增认证状态区, 认证启用时显示「登录」链接(/login)或「登出」按钮; 登录态由服务端注入(api/kline.py _get_dashboard_html 渲染 {{AUTH_STATE}}) + 新增 POST /logout 清 cookie; dev_server 兼容替换; 版本 1.3.1→1.3.2; 新增 test_auth.py 4项 |
| 2026-08-04 | — | Web 多 Tab 显示异常修复: 根因=API_TOKEN 占位符(your-*)被当作真实 token 启用认证, 浏览器未登录全部 API 401 被静默渲染成「暂无数据」; 修复: deps.py 占位符归一化为未配置(与 S3 语义一致) + shared.js 401 自动引导 /login; 版本 1.3.0→1.3.1; 新增 test_auth.py 4项 |
| 2026-08-03 | — | 安全审查修复: S1 dev_server路径遍历403 + S2 /login登录流程(替换无条件发cookie) + S3 启动API_TOKEN预检 + compare_digest防时序攻击 + 默认无认证警告; P1: 无Redis模式判空/Chief通知接线(notifier+symbol+price)/MACD-None不崩溃/凯利除零; 顺手: watchlist非法JSON 400 / bus health_check_interval / stdout日志脱敏 / env加载 / 版本残留1.1.8→1.3.0 / env.example重复变量 / GitHub链接; 新增 test_auth.py 9项 + 修复测试 4项 (284 total) |
| 2026-07-14 | `535b914` | 全模块评估+7项P1修复: 统一技术指标/Scanner并发/版本1.2.0/prefetch httpx/前端拆分/粗筛去重/dev_server补全mock |
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

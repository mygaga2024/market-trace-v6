# Planning Phase: market-trace-v6

You are creating an implementation plan for an epic. Your goal is to break down
the work into discrete, actionable tasks with clear dependencies.

## Your Mission

Create a detailed implementation plan including:
1. Task breakdown (~30 minutes per task)
2. File assignments for each task
3. Dependencies between tasks
4. Individual task files in the tasks/ directory

When complete:
1. Save plan to ".lisa/epics/market-trace-v6/plan.md"
2. Create task files in ".lisa/epics/market-trace-v6/tasks/"
3. Update the epic's .state file: set "planComplete" to true and "currentPhase" to "plan"

## CRITICAL CONSTRAINTS

**File System Boundaries:**
- Work ONLY within the project directory and its subdirectories
- DO NOT access files outside the project root
- DO NOT write to system temp directories
- For temporary files, use project-local directories only

## Plan Output Format

Save to: ".lisa/epics/market-trace-v6/plan.md"

```markdown
# Plan: market-trace-v6

## Overview
[Brief approach summary - 2-3 sentences]

## Tasks
1. [Task name] - tasks/01-task-name.md
2. [Task name] - tasks/02-task-name.md
3. [etc...]

## Dependencies
- 01: []
- 02: [01]
- 03: [01, 02]
[etc...]

## Risks
- [Risk and mitigation or "None identified"]
```

## Task File Format

Create each task file: ".lisa/epics/market-trace-v6/tasks/XX-task-name.md"

```markdown
# Task X: [Name]

## Status: pending

## Goal
[What this task accomplishes - 1 sentence]

## Files
- path/to/file.ts
- [more files...]

## Steps
1. [Concrete action]
2. [Concrete action]
3. [etc...]

## Done When
- [ ] [Specific, verifiable criterion]
- [ ] [more criteria...]
```

---

## Epic Spec

# Spec: Market Trace V6 全模块完成度评估与优化

## 目标

对项目所有模块（后端12模块 + 前端WebUI）进行系统性的完成度评估，识别未完工/待优化项，修复至同类产品最佳水平。

## 范围

### 评估范围

| 层级 | 模块 | 文件 |
|------|------|------|
| **后端-核心** | 消息总线 | `core/bus.py` |
| | LLM工厂+回退链 | `core/llm_factory.py` |
| | 策略定义 | `core/strategies.py` |
| | 风控管理 | `core/risk_manager.py` |
| | 熔断器 | `core/circuit_breaker.py` |
| | 仓位计算 | `core/position_sizing.py` |
| | 纸上交易 | `core/paper_trader.py` |
| | 案例记忆 | `core/memory.py` |
| | 通知 | `core/notifier.py` |
| | 数据模型 | `core/schema.py` |
| **后端-服务** | 诊股分析 | `services/analyzer.py` |
| | 数据预加载 | `services/prefetch.py` |
| | 市场扫描 | `services/scanner.py` |
| **后端-API** | 健康检查 | `api/health.py` |
| | 诊股选股 | `api/analyze.py` |
| | 回测 | `api/backtest.py` |
| | 风控 | `api/risk.py` |
| | K线渲染 | `api/kline.py` |
| | 持仓 | `api/watchlist.py` |
| | 安全+限流 | `api/deps.py`, `api/rate_limit.py` |
| **后端-Agent** | 宏观分析师 | `agents/macro_agent.py` |
| | 信号分析师 | `agents/signal_agent.py` |
| | 轨迹Agent | `agents/trace_agent.py` |
| | 风控Agent | `agents/risk_agent.py` |
| | 首席决策 | `agents/chief_analyst.py` |
| **后端-回测** | 回测运行器 | `backtest/runner.py` |
| | 策略回测 | `backtest/strategy_backtest.py` |
| | 策略管理 | `backtest/strategy_manager.py` |
| **后端-数据** | AkShare | `data_provider/akshare_impl.py` |
| | Tushare | `data_provider/tushare_impl.py` |
| | 容错 | `data_provider/fallback_handler.py` |
| **前端** | 仪表盘HTML | `templates/dashboard.html` |
| | JS交互 | `static/js/dashboard.js` |
| | 图表 | `static/js/charts.js` |
| | CSS样式 | `static/css/dashboard.css` |

### 评估维度

对每个模块从以下维度打分（1-5）：

1. **功能完整性** — 核心功能是否全部实现？有无 TODO/FIXME？
2. **健壮性** — 错误处理、边界条件、超时、重试是否到位？
3. **性能** — 有无性能瓶颈？并发、缓存、复用是否合理？
4. **代码质量** — 类型注解、文档、命名、重复代码
5. **前端体验** — UI 交互流畅度、数据渲染正确性、错误状态展示

### 输出物

1. **完成度矩阵** — 每个模块的5维评分 + 汇总
2. **问题清单** — 按优先级(P0/P1/P2/P3)列出所有待修项
3. **修复计划** — 按优先级逐一修复，每个修复后验证

## 验收标准

- [ ] 所有模块完成度评估报告已生成
- [ ] P0/P1 问题全部修复
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署验证通过
- [ ] 前端 Web 实测通过
- [ ] 版本号更新至 1.2.0

## 技术约束

- 不破坏现有模块间依赖和消息总线协议
- 不引入新的外部依赖（除非确有必要）
- 保持向后兼容，现有 API 返回值结构不变


---

## Research Findings

# Research: market-trace-v6

## Overview

Market Trace V6 是一个架构完善、功能完整的 A 股量化分析系统（44 个 Python 源文件 + 完整前端）。5 个 Agent（Macro/Signal/Trace/Risk/Chief）通过 Redis 消息总线协作，7 级 LLM 回退链做最终决策。所有核心模块均已实现，代码质量 B+，237 个测试通过。主要问题集中在：前端页面过长、部分模块代码重复、缺少实时 WebSocket 推送、Scanner 全市场扫描对无缓存股票依赖太强。

---

## Module Assessment Matrix

| 模块 | 文件 | 功能完整性 | 健壮性 | 性能 | 代码质量 | 综合 | 关键问题 |
|------|------|-----------|--------|------|---------|------|---------|
| **消息总线** | `core/bus.py` | 5/5 | 4/5 | 4/5 | 4/5 | 4.3 | Redis 单点故障无自动恢复，缺少 Stream 消费组 |
| **LLM工厂+回退链** | `core/llm_factory.py` | 5/5 | 5/5 | 4/5 | 5/5 | 4.8 | 7 级链路完美，多 LLM 共识机制好，`_clean_json_content` 健壮 |
| **策略定义** | `core/strategies.py` | 5/5 | 4/5 | 4/5 | 4/5 | 4.3 | 7 个策略统一注册，`_calc_atr` 向量化比 backtest 版优 |
| **风控管理** | `core/risk_manager.py` | 4/5 | 4/5 | 3/5 | 4/5 | 3.8 | 三级风险 + 自愈 + 仓位加权完整；Redis 重依赖，无本地降级 |
| **熔断器** | `core/circuit_breaker.py` | 4/5 | 4/5 | 4/5 | 5/5 | 4.3 | 三态实现标准；缺少滑动窗口统计（用简单计数器） |
| **仓位计算** | `core/position_sizing.py` | 4/5 | 3/5 | 5/5 | 4/5 | 4.0 | 凯利+等权重+风险平价；缺少 VaR/CVaR 和组合优化 |
| **纸上交易** | `core/paper_trader.py` | 5/5 | 4/5 | 4/5 | 5/5 | 4.5 | 文件持久化、多账户、市价估值、HOLD 日志，功能完善 |
| **案例记忆** | `core/memory.py` | 3/5 | 3/5 | 3/5 | 4/5 | 3.3 | 内存向量检索，无持久化；案例缺乏真实 outcome 反馈闭环 |
| **通知** | `core/notifier.py` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | WxPusher 单通道，缺少钉钉/飞书/邮件 |
| **数据模型** | `core/schema.py` | 5/5 | 5/5 | 5/5 | 5/5 | 5.0 | 完善的数据交换协议，dataclass 规范 |
| **共享决策引擎** | `core/chief_decision.py` | 5/5 | 4/5 | 5/5 | 5/5 | 4.8 | 双路径共用 + 三路分支(critical→WAIT/warning→降权/正常→LLM) |
| **诊股分析** | `services/analyzer.py` | 5/5 | 4/5 | 4/5 | 4/5 | 4.3 | 技术指标齐全(MA/RSI/MACD/Boll/KDJ/ATR/SR)；`_calc_macd` 与 signal_agent 重复 |
| **数据预加载** | `services/prefetch.py` | 4/5 | 3/5 | 3/5 | 3/5 | 3.3 | 热门并发+温数据队列+定时刷新；aiohttp 未用，用同步 requests |
| **市场扫描** | `services/scanner.py` | 4/5 | 3/5 | 2/5 | 4/5 | 3.3 | 两阶段粗筛+深度策略；5000+ 全量并发创建 create_task 过多 |
| **健康检查** | `api/health.py` | 4/5 | 4/5 | 5/5 | 4/5 | 4.3 | 公开/认证双端点完善；version 硬编码 1.1.8 与其他不一致 |
| **诊股选股** | `api/analyze.py` | 5/5 | 3/5 | 3/5 | 4/5 | 3.8 | 诊股/选股/扫描/纸上交易/智能扫描 6 个端点；`POST /analyze` 应为 GET |
| **回测** | `api/backtest.py` | 4/5 | 3/5 | 3/5 | 4/5 | 3.5 | 汇总/策略列表/启用/滚动/手动 5 个端点；同步阻塞回测应改为后台任务 |
| **风控** | `api/risk.py` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | 状态/历史/仓位建议 3 个端点；仓位建议参数过多 |
| **K线渲染** | `api/kline.py` | 4/5 | 4/5 | 4/5 | 4/5 | 4.0 | K线 JSON/SVG 迷你图/仪表盘 HTML 3 个端点；模板热加载 |
| **持仓** | `api/watchlist.py` | 4/5 | 3/5 | 3/5 | 4/5 | 3.5 | 增删查完整；Sina 实时价 + K线缓存兜底 |
| **安全+限流** | `api/deps.py`, `api/rate_limit.py` | 4/5 | 4/5 | 4/5 | 4/5 | 4.0 | Bearer Token + httpOnly Cookie + 120rpm 限流 |
| **报告路由** | `api/reports.py` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | Agent报告/决策CRUD完整 |
| **市场指数** | `api/market_index.py` | 未读 | - | - | - | ? | 大盘指数+涨跌家数端点 |
| **宏观Agent** | `agents/macro_agent.py` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | RAI 指数 + 板块动量；数据源单一(仅 AkShare) |
| **信号Agent** | `agents/signal_agent.py` | 5/5 | 4/5 | 4/5 | 5/5 | 4.5 | MA/MACD/RSI/背离完整；`_calc_macd` 与 analyzer 重复 |
| **轨迹Agent** | `agents/trace_agent.py` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | 量价分析替代资金流向(东财WAF降级) |
| **风控Agent** | `agents/risk_agent.py` | 5/5 | 4/5 | 4/5 | 5/5 | 4.5 | 逻辑冲突/顶背离/ATR止损/单日熔断/连续下跌 5 层检查 |
| **首席决策** | `agents/chief_analyst.py` | 5/5 | 4/5 | 4/5 | 5/5 | 4.5 | 三报告齐备触发 + 锁保护 + 决策历史 |
| **Agent基类** | `agents/base_agent.py` | 5/5 | 4/5 | 4/5 | 5/5 | 4.5 | 心跳+背压+宕机检测完善 |
| **回测运行器** | `backtest/runner.py` | 5/5 | 4/5 | 4/5 | 5/5 | 4.5 | 多仓位+止盈止损+基准对比+CAPM指标，功能完善 |
| **策略回测** | `backtest/strategy_backtest.py` | 4/5 | 3/5 | 3/5 | 3/5 | 3.3 | 网格搜索优化；`_calc_rsi`/`_calc_atr` 与 core/strategies.py 重复 |
| **策略管理** | `backtest/strategy_manager.py` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | 健康评估+连续失败追踪；不自动禁用(改为仅警告) |
| **AkShare** | `data_provider/akshare_impl.py` | 5/5 | 4/5 | 3/5 | 4/5 | 4.0 | 反爬+代理+延迟，611 行实现完整 |
| **容错** | `data_provider/fallback_handler.py` | 4/5 | 4/5 | 4/5 | 4/5 | 4.0 | 多源切换+缓存降级+数据缺失告警 |
| **数据库** | `db/database.py` | 4/5 | 4/5 | 4/5 | 4/5 | 4.0 | SQLAlchemy 异步 + 完整 CRUD + 统计 |
| **前端-Dashboard** | `templates/dashboard.html` | 4/5 | 3/5 | 3/5 | 2/5 | 3.0 | 功能全但 ~800 行 HTML 单文件，CSS 内联 |
| **前端-JS** | `static/js/dashboard.js` | 4/5 | 3/5 | 3/5 | 2/5 | 3.0 | 1505 行单一文件，Tab 切换 + 轮询 + 表单交互；代码量大 |
| **前端-图表** | `static/js/charts.js` | 4/5 | 3/5 | 4/5 | 4/5 | 3.8 | lightweight-charts 封装完善 |

---

## Issue Inventory (by priority)

### P0 - Critical
无。所有核心功能均可运行，无崩溃级 bug。

### P1 - High (显著改进空间)

- [ ] **Scanner 全市场并发爆炸** — `services/scanner.py:325`: smart_scan 对全部 5000+ 股票同时 `create_task`，可能耗尽 asyncio 资源。建议分批（每批 200 只）。
- [ ] **`_calc_macd`/`_calc_rsi`/`_calc_atr` 三处重复** — `services/analyzer.py`, `agents/signal_agent.py`, `backtest/strategy_backtest.py` 各自实现。统一切到 `core/strategies.py`。
- [ ] **数据预加载用同步 requests** — `services/prefetch.py:282/300`: `_fetch_name_via_sina` 和 `fetch_stock_price_via_sina` 用 `requests.get` + `asyncio.to_thread`，应改 httpx AsyncClient。
- [ ] **前端单文件过大** — `dashboard.js` 1505 行、`dashboard.html` ~800 行。维护困难，建议按 Tab 拆分。
- [ ] **回测为同步阻塞** — `api/backtest.py:29`: `GET /backtest/summary` 在请求线程中同步跑回测，应改为 `asyncio.to_thread` 或后台任务。
- [ ] **Redis 无本地降级** — 所有模块强依赖 Redis。Redis 不可用时系统基本瘫痪。应增加内存回退（已经有 `if not bus` 分支但不完整）。
- [ ] **版本号不一致** — `main.py:315` version="1.1.8"，`PROJECT_STATUS.md` 写 1.1.9，`api/health.py:43` 也写 1.1.8。
- [ ] **案例记忆无持久化** — `core/memory.py` 纯内存存储，重启丢失所有案例。应对接 DB。
- [ ] **无实时 WebSocket 推送** — 前端靠 30s 轮询获取状态，诊股结果也无法实时推送。

### P2 - Medium

- [ ] **`POST /analyze/{symbol}` 语义不当** — 诊股是只读操作，应为 GET。
- [ ] **Scanner fallback 粗筛逻辑硬编码** — `api/analyze.py:84-91` 重复了 `services/scanner.py:183-196` 的粗筛条件。
- [ ] **熔断器无滑动窗口** — 用简单失败计数，无法区分偶发故障和持续故障。
- [ ] **无 CI/CD 配置** — 没有 GitHub Actions 或其他 CI pipeline。
- [ ] **前端 CSS 内联在 HTML** — 应独立 CSS 文件，`static/css/dashboard.css` 存在但未充分利用。
- [ ] **LLM prompt 中 `risk` Agent 未在四维投票框架中出现** — 虽然 risk 有特殊处理，但 prompt 未提及 risk 的权重。

### P3 - Low

- [ ] **`core/log_filter.py` 未充分使用** — loguru filter 只做脱敏，可增强结构化日志。
- [ ] **`config/settings.yaml` 注释不足** — 部分配置项含义不明确。
- [ ] **`data_provider/base.py` 未完整读取** — 基类抽象层可能需要检查。
- [ ] **`docs/TODOLIST.md` 中仍有未完成项**

---

## Architecture Notes

### 整体架构
```
Redis (MessageBus)
  ├─ MacroAgent → 定时拉取宏观数据 → RAI 指数
  ├─ SignalAgent → 监听 DATA_UPDATED → 技术指标分析
  ├─ TraceAgent → 监听 DATA_UPDATED → 量价异动检测
  ├─ RiskAgent → 监听所有报告 → 5层风控检查 → 一票否决
  └─ ChiefAnalyst → 收集报告 → 调用 LLM 回退链 → 最终决策

FastAPI (Web Layer)
  ├─ /health, /health/detail → 健康检查
  ├─ /analyze/{symbol} → 诊股 (复用 Agent 逻辑)
  ├─ /screen/{strategy} → 选股
  ├─ /scan/{strategy}, /scan/smart → 全市场扫描
  ├─ /backtest/* → 回测
  ├─ /risk/* → 风控
  └─ / → 仪表盘 (templates/dashboard.html)
```

### 关键设计决策
1. **双路径决策**: Agent 事件路径 + Web API 路径通过 `core/chief_decision.py` 共用决策引擎
2. **多 LLM 共识**: 7 级回退链 + 2 LLM 共识/高置信度单 LLM 直接采纳
3. **风控为硬约束**: RiskAgent 有一票否决权，critical 直接 WAIT
4. **统一策略注册**: `core/strategies.py` 的 STRATEGIES 字典被诊股/选股/回测共用

### 耦合度分析
- `services/analyzer.py` 耦合最高：依赖 bus/config/llm_chain/prefetch
- `core/llm_factory.py` 相对独立
- `backtest/` 模块与 core/strategies.py 有代码重复但不共享函数

---

## Relevant Files

All 44 source files assessed:

**core/** (13): `bus.py`, `llm_factory.py`, `strategies.py`, `risk_manager.py`, `circuit_breaker.py`, `position_sizing.py`, `paper_trader.py`, `memory.py`, `notifier.py`, `schema.py`, `chief_decision.py`, `log_filter.py`, `__init__.py`

**services/** (4): `analyzer.py`, `prefetch.py`, `scanner.py`, `__init__.py`

**api/** (13): `health.py`, `analyze.py`, `backtest.py`, `risk.py`, `kline.py`, `watchlist.py`, `deps.py`, `rate_limit.py`, `reports.py`, `replay.py`, `market_index.py`, `paper.py`, `__init__.py`

**agents/** (7): `base_agent.py`, `macro_agent.py`, `signal_agent.py`, `trace_agent.py`, `risk_agent.py`, `chief_analyst.py`, `__init__.py`

**backtest/** (5): `runner.py`, `strategy_backtest.py`, `strategy_manager.py`, `replay.py`, `__init__.py`

**data_provider/** (5): `base.py`, `akshare_impl.py`, `tushare_impl.py`, `fallback_handler.py`, `__init__.py`

**db/** (3): `database.py`, `models.py`, `__init__.py`

**Frontend** (4): `templates/dashboard.html`, `static/js/dashboard.js`, `static/js/charts.js`, `static/css/dashboard.css`

**Root** (3): `main.py`, `dev_server.py`, `config/settings.yaml`

## Existing Patterns

1. **Pub/Sub Agent 通信**: 所有 Agent 继承 `BaseAgent`，通过 Redis Pub/Sub 收发消息，含心跳+宕机检测
2. **LLM 回退链**: Chain of Responsibility 模式，7 级 LLM → 纯规则降级
3. **双路径决策**: Agent 事件路径和 Web API 路径通过 `chief_decision.py` 共用决策引擎
4. **统一策略注册**: `core/strategies.py` STRATEGIES 字典被诊股/选股/回测三方共用
5. **dataclass 数据协议**: `core/schema.py` 定义所有 Agent 间通信数据结构
6. **三态熔断器**: CLOSED → OPEN → HALF_OPEN，保护 LLM/数据源调用
7. **数据源降级链**: Tushare → AkShare → Redis 缓存 → None
8. **app.state 共享状态**: FastAPI lifespan 初始化 bus/db/config/llm_chain，路由通过 `request.app.state` 访问
9. **Redis 优先 + 本地降级**: 大多数模块有 `if not bus` 的本地回退分支
10. **30s 轮询前端**: 前端通过定时 fetchAuth 获取服务端状态

## Recommendations

### 实施优先级
1. **统一指标计算** (P1) — 消除 `_calc_macd`/`_calc_rsi`/`_calc_atr` 三处重复，统一切到 `core/strategies.py`
2. **Scanner 并发优化** (P1) — 分批创建 task，避免 5000+ 并发
3. **版本号统一** (P1) — 所有位置更新到 1.2.0
4. **prefetch 迁移到 httpx** (P1) — 替换同步 requests 调用
5. **前端拆分** (P1) — dashboard.js 按功能拆分为多个模块
6. **回测异步化** (P1) — GET /backtest/summary 改为后台任务
7. **代码去重** (P2) — Scanner 粗筛逻辑去重

### 不改的部分
- LLM 回退链架构（已成熟稳定）
- Agent 间消息协议（schema.py 无需改动）
- 数据库 schema（字段齐全）
- 纸上交易模块（功能完善）
- 风控五层检查逻辑（成熟）


---

## Instructions

1. Review the spec and research findings
2. Break work into ~30 minute tasks (typically 3-10 tasks)
3. Define clear dependencies (which tasks must complete before others)
4. Create plan.md with task list and dependencies
5. Create individual task files with detailed steps
6. Update the .state file to mark planning complete
7. Report summary: number of tasks created and key dependencies

Guidelines:
- Keep tasks focused (1-5 files per task)
- Make tasks independently verifiable
- Order dependencies logically
- Don't over-engineer - simple is better

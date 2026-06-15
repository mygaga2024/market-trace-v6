# Market Trace V6.0 — 开发进度

> 最后更新：2026-06-11
> 当前版本：v1.1.8 — 持仓列表实时价格 + 诊股跳转 + Tab自动聚焦

---

## 开发规范

### 任务交付标准
1. **三地同步**：本地 → GitHub → NAS 绿联 GGUG (10.10.10.130:16011)
2. **NAS 实际环境测试**：所有测试必须在 NAS Docker 容器内运行 `docker exec mt6-app python -m pytest tests/ -q`，确认通过后方可交付
3. **API 端点验证**：部署后 curl 验证关键端点 (`/health`, `/health/detail`, `/status`)
4. **记录更新**：同步更新 `PROGRESS.md` 和 `docs/OPS.md`

### 部署流程
```bash
# 1. 本地提交 & 推送 GitHub
git add -A && git commit -m "..." && git push origin main

# 2. 全量同步到 NAS
tar czf /tmp/mt6.tar.gz --exclude='.git' --exclude='env' --exclude='logs' --exclude='.pytest_cache' --exclude='data' .
cat /tmp/mt6.tar.gz | ssh nas "cd /volume1/docker/market-trace-v6 && docker compose down; tar xzf - && docker compose up -d --build"

# 3. NAS 运行测试
ssh nas "docker exec mt6-app python -m pytest tests/ -q"

# 4. 验证 API
curl http://10.10.10.130:19377/health
curl http://10.10.10.130:19377/health/detail
```

---

## v1.1.8 持仓列表实时价格 + 诊股跳转 + Tab聚焦 (2026-06-11)

### 修复内容

#### 持仓列表实时价格
- **`api/watchlist.py`** — 重构价格获取逻辑：**新浪实时优先 → K线缓存兜底**。原逻辑先读 `market:raw:` K线缓存，缓存命中后实时接口被跳过，导致显示日K收盘价而非实时价。改为并发调新浪 `hq.sinajs.cn`（Semaphore(3) 限流），失败时回退 K线缓存。
- **实测**：`600036` 修复前显示 `38.90`（K线缓存），修复后 `38.76`（新浪实时）。

#### 诊股跳转聚焦
- **`static/js/dashboard.js`** — `analyzeStock()` 点击瞬间 `scrollIntoView` 到 spinner 区域，不等 API 返回即跳转
- 修复过程中发现 `chart-container--hidden` 类包含 `display: none`，`scrollIntoView` 在元素隐藏时无效，已修正调用顺序

#### Tab切换自动滚动 + 卡片跳转
- **`static/js/dashboard.js`** — `switchTab()` 末尾统一加 `scrollIntoView('#tab-panel')`，覆盖所有 tab 切换入口
- 新增 4 个卡片→Tab 点击跳转：AI决策链→决策历史、最新决策→决策历史、运行Agent→健康检查、RAI→宏观报告（风控闭环→风控历史已有）

### 待办记录
- **`docs/TODOLIST.md`** — 新增 Web UI 优化 5 项：`load()` 解耦、持仓刷新反馈、渲染去重、Tab 缓存过期、静态文件版本号

### 测试验证
- NAS API 验证：`/watchlist` 8只持仓实时价正常、`/analyze/000001` 正常、`/health` ok
- 静态文件：`dashboard.js` 200，scrollIntoView + 卡片跳转代码已部署

### 改动文件清单
| 类型 | 文件 |
|------|------|
| 修改 | `api/watchlist.py`, `static/js/dashboard.js` |
| 记录 | `docs/TODOLIST.md` |

### 提交记录
```
7e06786 fix: tab切换后自动滚动+卡片点击跳转到对应tab
4f38d81 fix: 诊股点击瞬间立即跳转-不等接口返回
6ba421f fix: scrollIntoView用requestAnimationFrame确保DOM布局完成后滚动
3b5b78f fix: 诊股跳转-修复scrollIntoView在元素隐藏前调用导致无效
b2f537e feat: 诊股后自动滚动到K线图区域
7dec35e fix: 持仓列表改为新浪实时价格优先，K线缓存降级兜底
```

---

## v1.1.7 持仓列表价格刷新按钮 (2026-06-10)

### 问题诊断
- Web 页面打开时持仓列表自动加载，但价格/涨跌幅依赖 Redis 缓存 `market:raw:{symbol}`
- 若缓存未就绪或股票不在 `stock_pool` 中，价格显示为 `—`
- 缺少手动触发价格刷新的入口

### 修复内容
- **`templates/dashboard.html`** — 持仓列表"添加"按钮旁新增 `↻` 刷新按钮
- **`static/js/dashboard.js`** — 新增 `refreshWatchlist()` 函数，独立请求 `/watchlist` 并重绘持仓列表，含加载态和错误兜底

### 测试验证
- NAS 测试: 184 passed, 2 skipped
- API 验证: `/health` ok, `/health/detail` ok (Redis/DB/5 Agent 全部连接)
- 页面验证: 刷新按钮 `↻` 已在 NAS 部署的页面中正常显示

---

## v1.1.6 股票名称显示修复 (2026-06-09)

### 问题诊断
- Web 页面持仓列表无股票名称，诊股结果也无名称
- 根因：akshare 东财 `stock_zh_a_spot_em` 接口被 WAF 拦截，`prefetch_stock_names` 启动时失败，Redis `stock:names` 缓存为空
- `api/watchlist.py` 的 `get_watchlist` 和 `add_to_watchlist` 仅从 DB 取 name，未从缓存补充

### 修复内容
- **`api/watchlist.py`** — `get_watchlist` DB 无 name 时调用 `get_stock_name()` 从缓存补充；`add_to_watchlist` 请求无 name 时自动查找
- **`services/prefetch.py`** — 新增 `_fetch_name_via_sina()` 用新浪 `hq.sinajs.cn` 实时查询单只名称；`get_stock_name` 增加进程内缓存，链式查询（进程缓存 → Redis → 新浪）；`prefetch_stock_names` akshare 失败时用新浪逐只查询并批量缓存到 Redis

### 测试验证
- NAS 测试: 184 passed, 2 skipped
- API 验证: `/watchlist` 7 只持仓全部显示名称（中矿资源、新安股份、双欣材料、盛美上海、上海瀚讯、盛新锂能、泰豪科技）
- 名称缓存: 48 只股票名称已缓存到 Redis

---

## v1.1.5 WebUI 功能完善 + 前端开发工具链 (2026-06-09)

### WebUI 功能完善

#### 风控闭环面板
- **`static/js/dashboard.js`** / **`templates/dashboard.html`** — 主网格新增"风控闭环"卡片，实时显示风险等级（正常/关注/危险）、否决次数、事件数，点击跳转风控历史 Tab
- Tab 栏新增 **"风控历史"** Tab，展示否决事件列表（时间/级别/规则/股票/详情）
- 对接后端 `/risk/status`, `/risk/overrides` 端点

#### 仓位计算器
- **`static/js/dashboard.js`** — 诊股成功后自动调用 `/risk/position/{symbol}`，结果区追加仓位建议（股数+金额+风险权重）

#### 策略管理面板
- **`static/js/dashboard.js`** — 回测 Tab 顶部新增策略状态表格（状态/连续失败/评分）+ "手动回测"按钮 + 禁用策略的"启用"按钮
- 对接 `/backtest/strategies`, `/backtest/run`, `/backtest/strategies/{name}/enable`

#### 决策详情弹窗
- **`templates/dashboard.html`** / **`static/js/dashboard.js`** — 决策历史每行可点击，弹出 modal 展示完整理由、证据来源、证据链、风控否决标记
- 对接 `/decisions/{id}` 端点

#### 持仓股票列表（本次新增）
- **`db/models.py`** — 新增 `WatchlistModel` 表（symbol/name/notes/added_at）
- **`db/database.py`** — 新增 `get_watchlist()`, `add_to_watchlist()`, `remove_from_watchlist()` CRUD
- **`api/watchlist.py`** — **新文件**。`GET /watchlist`, `POST /watchlist`, `DELETE /watchlist/{symbol}` 端点
- **`main.py`** — 注册 watchlist 路由
- **`templates/dashboard.html`** / **`static/js/dashboard.js`** — 持仓列表卡片（输入框+添加按钮+列表），每行显示名称/代码/价格/涨跌，点击诊股，点击 x 删除

#### 股票名称显示（本次新增）
- **`services/prefetch.py`** — `prefetch_stock_names()` 启动时批量调用 AkShare 获取 A 股名称缓存到 Redis；`get_stock_name()` 按 symbol 查询
- **`services/analyzer.py`** — `analyze_single()` 响应新增 `name` 字段
- **`api/analyze.py`** — `screen_stocks()` 每个结果新增 `name` 字段
- **前端** — 诊股结果区上方显示名称+代码，选股结果每行显示名称

#### 模板热加载
- **`api/kline.py`** — `_get_dashboard_html()` 支持文件 mtime 检测自动刷新模板缓存，支持 `MT6_DEV=1` 强制每次重新读取

### 前端开发工具链（本次新增）
- **`dev_server.py`** — **新文件**。独立前端开发服务器，`python3 dev_server.py` 瞬时启动，零依赖（无需 Redis/DB/Agent），全部 API 返回 mock 数据，前端所有按钮/Tab/弹窗可交互验证
- **`tests/test_webui.py`** — **新文件**。15 项前端自动化验证：HTML 结构、静态文件、JS 语法、CSS 类名、JS-ID 引用完整性、dev_server mock 覆盖
- 日常开发流程：
  ```bash
  python3 dev_server.py                     # 瞬时启动，浏览器验证前端交互
  python3 -m pytest tests/test_webui.py -q  # 2 秒前端结构验证
  python3 -m pytest tests/ -q               # 全量 186 测试提交前验证
  ```

### 测试结果
- **186 passed**, 0 failed, 100% 通过率 (171 backend + 15 webui)

### 改动文件清单
| 类型 | 文件 |
|------|------|
| 新增 | `api/watchlist.py`, `dev_server.py`, `tests/test_webui.py` |
| 修改 | `api/analyze.py`, `api/kline.py`, `db/database.py`, `db/models.py`, `main.py`, `services/analyzer.py`, `services/prefetch.py`, `static/css/dashboard.css`, `static/js/dashboard.js`, `templates/dashboard.html` |

---

## v1.1.4 仪表盘修复与部署优化 (2026-06-09)

### 仪表盘修复
- **`static/js/dashboard.js`** — 修复健康检查与主轮询使用错误端点的问题：
  - `load()` 主轮询从 `/health` 改为 `/health/detail`，Agent 心跳灯、LLM 链数据恢复正常
  - 健康检查 Tab fetcher 同样改为 `/health/detail`，Redis/数据库/Agent 运行数正确渲染
  - `/status` 请求增加 `r.ok` 检查，避免非 2xx 响应 JSON 解析异常

### Docker 部署优化
- **`docker-compose.yaml`** — 新增 `./static:/app/static` 卷挂载，静态文件修改后仅需 `docker compose restart`，无需重建镜像
- **`docs/OPS.md`** — 更新为绿联 NAS GGUG (10.10.10.130) 配置，新增 SSH 连接信息、快速 `scp` 部署命令

### 基础设施
- SSH 密钥 `id_ed25519_nas` 已部署至 NAS，支持免密登录 `ssh nas`
- 三地同步流程：本地 → GitHub (排除敏感文件) → NAS

---

## v1.1.3 安全与健壮性优化 (2026-06-08)

### 安全性加固
- **`api/deps.py`** — Session token 改用 `secrets.token_hex(32)` 安全生成，不再从 API_TOKEN 通过 sha256 派生，避免基于 API Token 的 session 伪造风险
- **`api/health.py`** — 拆分健康检查端点：
  - `/health` (公开) 仅返回 `status`/`version`/`uptime`，不暴露 Redis/DB/Agent 等内部架构
  - `/health/detail` (需认证) 保留完整健康信息给运维调试

### 健壮性修复
- **`services/prefetch.py`** — asyncio 原语（Semaphore/Queue/Event）从模块级静态初始化改为懒初始化 `_ensure_asyncio_primitives()`，避免绑定到错误的事件循环
- **`core/llm_factory.py`** — LLM JSON 解析失败时区分重试与永久错误，避免无意义重试；`RuleBasedAnalyzer` 集成 Risk 报告评分
- **`core/memory.py`** — 案例检索返回 `replace()` 副本而非修改共享对象，避免并发下 `similarity_score` 污染

### 策略优化
- **`agents/risk_agent.py`** — 止损检查替换为顶背离检测（`_check_bearish_divergence`），熔断方向修复（仅下跌方向触发）

### 时区规范化
- **`core/schema.py`** / **`core/notifier.py`** — 所有 `datetime.now()` 统一为 `datetime.now(timezone.utc)`，eliminate naive datetime 的时区歧义
- **`main.py`** — 回测调度器使用 `.astimezone()` 本地时区 aware datetime

### 启动与测试
- **`main.py`** — 启动时检查 LLM API Key 配置状态，输出 `⚠️` 警告
- **`tests/test_web.py`** — 新增 `test_health_detail` 测试认证端点的完整返回

### 测试结果
- **171 passed**, 0 failed, 100% 通过率

---

## v1.1.2 架构拆分与优化 (2026-06-02)

### API 架构拆分
- **`main.py` → `api/` + `services/`**：把 300+ 行路由/业务逻辑拆分到独立模块
  - `api/`: health, reports, analyze, backtest, risk, kline, deps（7 个路由模块）
  - `services/`: analyzer（诊股分析）, prefetch（股票池预加载缓存）
- **`app.state` 模式**：lifespan 中初始化共享状态（bus, db, config, llm_chain, risk_manager），路由通过 `request.app.state` 访问，不再使用模块级全局变量

### 性能优化
- `agents/signal_agent.py` `_calc_ma` — Python for 循环改为 `np.convolve` 向量化，MA 大周期计算性能显著提升

### Bug 修复
- `tests/test_base_agent.py` — `TestAgent` → `DummyAgent`，修复 PytestCollectionWarning
- `tests/test_web.py` — 适配架构拆分：fixture 通过 `app.state` 注入 mocks
- `data_provider/base.py` — `datetime.now()` → `datetime.now(timezone.utc)` 时区规范化
- `data_provider/fallback_handler.py` — `_reset_unavailable` 按 symbol 精确重置，避免误清所有计数
- `db/database.py` — 新增 `health_check()` 和 `get_decision_by_id()` 公开方法

### Docker
- `docker-compose.yaml` — 添加 `TZ=Asia/Shanghai` 时区环境变量

### 仪表盘修复
- `api/health.py` `llm_chain` 返回字段修复：`configured` → `api_key_configured` + `provider` + `model`，解决仪表盘 AI 决策链显示掉线的问题

### 选股策略优化
- `services/analyzer.py` + `backtest/strategy_backtest.py`
  - **主力介入**：量比基线 5日→20日均量，新增 5日涨幅>2% 条件
  - **超跌反弹**：新增止跌回升确认（今日收阳）
  - **风险预警**：新增续跌确认 + 放量确认（≥1.2 倍 20 日均量）
  - **强势突破**：原逻辑已严谨，无改动

### 测试结果
- **170 passed**, 0 failed, 100% 通过率

---

## 总览

| 阶段 | 名称 | 状态 | 开始日期 | 完成日期 |
|------|------|------|----------|----------|
| 01 | 项目骨架与环境 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 02 | 数据访问层与事件基础 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 03 | Agent 通信骨架与心跳 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 04 | 业务 Agent 实现 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 05 | Chief Analyst + LLM 回退链 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 06 | 数据库与案例库 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 07 | Web 服务与集成 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 08 | 回测与仿真 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| 09 | 测试、日志优化与验收 | ✅ 已完成 | 2026-05-27 | 2026-05-27 |
| **修复** | **19 项代码问题集中修复与安全强化** | **✅ 已完成** | **2026-05-28** | **2026-05-28** |
| **10** | **回测闭环 + 风控闭环 + K线可视化** | **✅ 已完成** | **2026-06-01** | **2026-06-01** |

---

## v1.1.1 安全加固 (2026-06-01)

### 认证安全
- **httpOnly Cookie 认证**：仪表盘认证改用 `Set-Cookie: mt6_session`（httpOnly + SameSite=strict），不再暴露 token 到 JavaScript/DOM
- **错误信息脱敏**：所有 API 错误响应不再泄露内部异常详情，改用通用中文提示
- **健康检查脱敏**：`/health` 返回仅显示 `configured: true/false`，不再泄露 provider/model 名称

### Docker 安全
- **非 root 运行**：`USER appuser` (UID 1000，匹配 NAS 宿主用户 `mygaga`)，避免容器内 root 权限
- **健康检查简化**：从 Python+httpx 改为 `curl -sf`，减少依赖和启动开销
- **LLM 优雅关闭**：lifespan shutdown 调用 `llm_chain.close()` 释放 HTTP 连接池

### Bug 修复
- 修复 `@app.get("/risk/position/{symbol}")` 装饰器被误删
- 修复 `RuleBasedAnalyzer` weights 配置路径 (`fallback.weights` → `weights`)
- 修复 `_prefetch_stock_pool` 中 bus 为 None 时的空指针
- 移除未使用的 `primary_provider` 变量

### LLM 提示词优化
- 决策 prompt 新增当前 UTC 时间，辅助 AI 判断市场时段

---

## v1.1.0 更新内容 (2026-06-01)

### 回测闭环
- `backtest/strategy_manager.py` — 策略生命周期管理器
  - 活跃/禁用状态追踪（Redis 持久化）
  - 连续失败计数，超阈值自动禁用
  - 健康评估（胜率/评分/交易数）
  - 新增 3 端点: `GET /backtest/strategies`, `POST /backtest/strategies/{name}/enable`, `POST /backtest/run`
- `backtest/strategy_backtest.py` — 支持 `active_strategies` 筛选
- `config/settings.yaml` — 新增 `backtest.schedule` 定时调度配置

### 风控闭环
- `core/risk_manager.py` — 风控闭环管理器
  - 三级风险状态: normal → elevated(3次警告) → critical(5次/critical事件)
  - 仓位风险加权: normal=1x, elevated=0.5x, critical=0.25x
  - 事件历史追踪
  - 新增 3 端点: `GET /risk/status`, `GET /risk/overrides`, `GET /risk/position/{symbol}`
- `agents/risk_agent.py` — 接入 RiskManager 自动记录否决事件

### K线可视化
- `static/js/charts.js` — 基于 lightweight-charts 的图表模块
  - 诊股页: K线蜡烛图 + 成交量副图（十字光标/缩放/平移）
  - 回测页: 策略夏普/胜率对比柱状图
- 新增端点: `GET /api/kline/{symbol}` — 返回 OHLCV JSON 数据

### 文档
- `docs/GLOSSARY.md` — 名词解释术语表（诊股/选股/回测/风控字段通俗化）

---

## 最终交付统计

| 指标 | 数值 |
|------|------|
| 源代码文件 | 28 个 |
| 测试文件 | 10 个 |
| 总测试数 | **170** |
| 测试通过率 | **100%** |
| GitHub Tags | v0.1 ~ v1.1.1 |

---

## 2026-05-28 代码审查与安全/功能修复

针对项目进行了全方位的代码审查，针对发现的 19 项问题（涉及安全隐患、逻辑漏洞、配置冗余及易用性问题）实施了集中修复并全量通过测试：

### 修复内容分类
1. **配置与 Docker 优化**：将 Redis 密码用`${REDIS_PASSWORD}`环境变量安全替代；把股票池从 `main.py` 抽离至 `config/settings.yaml`；修正 Docker 端口为 `19377`，引入非 root 用户 `appuser` 保障容器安全。
2. **安全改善**：为 `POST /analyze` 与 `POST /screen` 端点新增基于 Bearer Token 的 API 授权机制；收窄 `verify=False` 的 SSL 绕过范围，仅在存在 `HTTP_PROXY` 时对数据抓取库生效。
3. **核心业务逻辑 Bug 修复**：
   - 修正了回测（`backtest/runner.py`）中净值计算公式，改用最新市场价格计算持仓总市值，规避了由于使用持仓均价计算而导致的净值失真。
   - 修复了 `SimilarCase` 写入决策（`decision`）传参以及时区转换在 `fromisoformat` 时发生 tzinfo 解析崩溃的隐患。
   - 修复了 `ChiefAnalyst` 高并发环境下缓存字典引用清空导致报告丢失的隐患。
4. **代码清理与界面易用性**：移除了 `trace_agent` 死代码；复用了全局已初始化的 `bus` 总线以减轻资源开销；修正了 `RuleBasedAnalyzer` 实例化传参；仪表盘前端由全页刷新改为 `30s` 间隔的优雅局部刷新。
5. **Agent 行为限制**：为 `RiskAgent` 添加了 `event` 消息过滤机制，防止其误处理系统确认通知。

### 最终测试结果
- **总测试用例数**：146
- **通过率**：**100% (146 passed, 0 failed)**

---

### 仓库

<your-repo-url>

### 部署路径

```
/volume1/docker/market-trace-v6/
├── config/settings.yaml
├── env (手动创建)
├── docker-compose.yml
├── Dockerfile
├── logs/
├── data/
└── ...
```

### 部署命令

```bash
cd /volume1/docker/market-trace-v6
git clone <your-repo-url> .
cp env.example env
vi env   # 填入 API Keys
docker compose up -d
curl localhost:19377/health
```

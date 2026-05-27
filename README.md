# Market Trace V6.0

A/B 股量化分析系统 — 基于多 Agent 协作 + AI 多级回退链

**测试**: 145 passed ✅ | **Python**: 3.11+ | **部署**: Docker Compose

---

## 架构

```
[AkShare/XTick/Yquoter 数据适配器] → Redis Pub/Sub
                                         ↓
┌──────────┬───────────┬──────────┬──────────┐
│ Macro    │ Signal    │ Trace    │ Risk     │
│ Agent    │ Agent     │ Agent    │ Agent    │
│ (RAI)    │ (MA/MACD) │ (资金流)  │ (否决权)  │
└────┬─────┴─────┬─────┴────┬─────┴────┬─────┘
     └───────────┴──────────┴──────────┘
                       ↓
              Chief Analyst AI
    DeepSeek → Gemini → MiniMax → 纯规则加权
                       ↓
           Redis decision:final  ← 证据链
                       ↓
               FastAPI / SQLite / Loguru
```

## 核心链路

| 层级 | 说明 |
|------|------|
| **基准层** | 传统技术指标 (MA/MACD/RSI) 确定市场状态 |
| **变异层** | 资金流 (Level-2 近似) 与博弈数据捕捉非线性机会 |
| **AI 决策** | 多维度信息融合，输出概率分布 + 证据链 |
| **风控层** | 硬编码规则引擎，一票否决权 |

---

## 快速启动

### 1. 配置

```bash
cp env.example env
# 编辑 env，填入 API Key
```

### 2. Docker 部署 (绿联 NAS)

```bash
# 克隆到 NAS
cd /volume1/docker/market-trace-v6
git clone https://github.com/mygaga2024/market-trace-v6.git .

# 配置 API Key
vi env

# 启动
docker compose up -d
```

### 3. 验证

```bash
curl http://localhost:8000/health
```

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 系统健康 (Redis + DB + Agent 心跳 + LLM 提供商状态) |
| GET | `/status` | 状态概览 (决策统计 + 案例统计 + 最新决策) |
| GET | `/reports/{agent}` | 指定 Agent 报告列表 (分页 + 符号过滤) |
| GET | `/reports/{agent}/latest` | 指定 Agent 最新报告 |
| GET | `/decisions` | 决策历史列表 (分页 + 统计) |
| GET | `/decisions/{id}` | 完整决策详情 (含 evidence_chain) |

---

## LLM 多级回退链

```
请求 → DeepSeek (主力)
         ├─ OK → 返回 Decision {action, confidence, evidence_chain}
         └─ 熔断/超时/限频/5xx →
            Gemini (备用)
              ├─ OK → 返回 (provider=gemini)
              └─ 熔断/失败 →
                 MiniMax (三级兜底)
                   ├─ OK → 返回 (provider=minimax)
                   └─ 全部失败 →
                      纯规则加权 ★ CRITICAL
                      权重: macro=0.25 signal=0.25 trace=0.30 risk=0.20
```

每级独立: 超时 30s、最多 2 次重试、429 指数退避、熔断器(3 次失败→OPEN 60s)。

---

## 目录结构

```
market_trace_v6/
├── agents/               # Agent 逻辑
│   ├── base_agent.py     #   基类 (心跳/监听/背压/宕机检测)
│   ├── macro_agent.py    #   宏观 RAI 指数
│   ├── signal_agent.py   #   技术指标 + 背离检测
│   ├── trace_agent.py    #   资金异动 + Z-score
│   ├── risk_agent.py     #   硬编码风控 (一票否决)
│   └── chief_analyst.py  #   决策中枢 + LLM 回退
├── core/                 # 引擎底层
│   ├── bus.py            #   Redis 异步消息总线
│   ├── schema.py         #   数据协议 dataclasses
│   ├── circuit_breaker.py#   三态熔断器
│   ├── llm_factory.py    #   LLM 接口 + 回退链 + 纯规则
│   └── memory.py         #   案例库 (向量 + 余弦相似度)
├── data_provider/        # 数据访问层
│   ├── base.py           #   抽象基类
│   ├── akshare_impl.py   #   AkShare 异步 (反爬/熔断)
│   └── fallback_handler.py#  降级 → 缓存 → DATA_MISSING
├── db/                   # 持久化
│   ├── models.py         #   ORM (报告/决策/案例)
│   └── database.py       #   异步引擎 + CRUD 仓库
├── backtest/             # 回测
│   ├── replay.py         #   历史重放 (批量/实时)
│   └── runner.py         #   回测引擎 (夏普/最大回撤/胜率)
├── tests/                # 145 单元测试
├── config/settings.yaml  # 全配置驱动
├── main.py               # FastAPI 入口
├── docker-compose.yml    # Redis + App (1GB limit)
└── Dockerfile            # Python 3.11-slim
```

---

## 测试

```bash
# 安装依赖
pip install -r requirements.txt

# 全部测试
pytest tests/ -q
# 145 passed in ~7s
```

### 测试覆盖

| 模块 | 测试数 | 覆盖 |
|------|--------|------|
| 数据访问层 | 32 | 符号标准化、K线转换、熔断、降级、缓存 |
| Agent 基类 | 14 | 心跳、订阅、背压、宕机检测、启停 |
| 业务 Agent | 35 | RAI、MA/MACD/RSI、背离、大单、冲突检测 |
| LLM 回退链 | 19 | 提示词、解析、回退路由、风控否决 |
| 数据库 | 14 | CRUD、分页、统计、边界 |
| Web API | 11 | 健康/状态/报告/决策端点 |
| 回测 | 20 | 重放、交易执行、夏普/回撤/胜率 |

---

## 配置 (config/settings.yaml)

所有参数可配置: LLM 三级供应商、熔断阈值、反爬延迟、Agent 阈值、数据源列表。

API Key 通过 `env` 文件注入 (gitignore 保护)，`${VAR}` 自动替换。

---

## 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 主力 AI 模型 |
| `GEMINI_API_KEY` | 备用 AI 模型 (OpenAI 兼容端) |
| `MINIMAX_API_KEY` | 三级备用 AI 模型 |
| `TUSHARE_TOKEN` | (可选) Tushare 数据源 |

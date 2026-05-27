# Market Trace V6.0

A/B 股量化分析系统 — 基于多 Agent 协作 + AI 多级回退链

## 架构

```
[数据源适配器] → Redis Pub/Sub
                    ↓
 ┌─────────┬──────────┬─────────┬─────────┐
 │Macro    │Signal    │Trace    │Risk     │
 │Agent    │Agent     │Agent    │Agent    │
 └────┬────┴────┬─────┴────┬────┴────┬────┘
      └─────────┴──────────┴─────────┘
                    ↓
            Chief Analyst AI
      DeepSeek → Gemini → MiniMax → 纯规则
                    ↓
              FastAPI / SQLite
```

## 快速启动

### 1. 配置 API Key

```bash
cp env.example env
# 编辑 env，填入 DeepSeek、Gemini、MiniMax 的 API Key
```

### 2. 启动

```bash
docker compose up -d
```

### 3. 验证

```bash
curl http://localhost:8000/health
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 系统健康检查（Redis 状态、Agent 心跳） |
| GET | `/status` | 系统状态概览 |

## 技术栈

- **语言**: Python 3.11+ (全异步 asyncio)
- **消息总线**: Redis Pub/Sub + Stream
- **Web 框架**: FastAPI + Uvicorn
- **数据源**: AkShare (适配器模式，预留多源切换)
- **AI 决策**: 多级链式回退 (DeepSeek → Gemini → MiniMax → 纯规则)
- **数据库**: SQLite (aiosqlite) + SQLAlchemy async
- **日志**: Loguru (500MB 轮换，7 天保留)
- **部署**: Docker Compose (单容器 ≤ 1GB 内存)

## 目录结构

```
market_trace_v6/
├── agents/          # Agent 逻辑模块
├── core/            # 引擎底层 (总线、Schema、熔断器)
├── data_provider/   # 数据访问层 (适配器模式)
├── db/              # 持久化存储
├── config/          # 配置文件
├── backtest/        # 回测与仿真
├── tests/           # 单元测试
├── logs/            # 日志 (git ignored)
├── data/            # 数据 (git ignored)
├── main.py          # 启动入口
├── docker-compose.yml
└── Dockerfile
```

## 环境变量

所有敏感配置通过 `env` 文件注入（不提交到 Git）。

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 主力 AI 模型 API Key |
| `GEMINI_API_KEY` | 备用 AI 模型 API Key |
| `MINIMAX_API_KEY` | 三级备用 AI 模型 API Key |
| `TUSHARE_TOKEN` | (可选) Tushare 数据源 Token |

## 开发阶段

| 阶段 | 名称 | 状态 |
|------|------|------|
| 01 | 项目骨架与环境 | ✅ |
| 02 | 数据访问层与事件基础 | ⬜ |
| 03 | Agent 通信骨架 | ⬜ |
| 04 | 业务 Agent 实现 | ⬜ |
| 05 | Chief Analyst + LLM 回退链 | ⬜ |
| 06 | 数据库与案例库 | ⬜ |
| 07 | Web 服务与集成 | ⬜ |
| 08 | 回测与仿真 | ⬜ |
| 09 | 测试、日志优化与验收 | ⬜ |

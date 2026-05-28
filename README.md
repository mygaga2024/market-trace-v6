# Market Trace V6.0

A/B 股量化分析系统 — 多 Agent 协作 + AI 多级回退链

**测试**: 146 passed ✅ | **Python**: 3.11+ | **部署**: Docker Compose | **端口**: 19377

---

## 仪表盘

打开浏览器访问 `http://<your-nas-ip>:19377`

暗色交易面板风格，实时显示 RAI 风险偏好指数、5 个 Agent 运行状态、LLM 三级链、最新决策。每 30 秒自动刷新。

---

## 架构

```
[数据适配器 (多源备选)]
           ↓
      Redis 消息总线
           ↓
┌──────────┬───────────┬──────────┬──────────┐
│ Macro    │ Signal    │ Trace    │ Risk     │
│ (RAI)    │ (MA/MACD) │ (量价异动) │ (否决权)  │
└────┬─────┴─────┬─────┴────┬─────┴────┬─────┘
     └───────────┴──────────┴──────────┘
                    ↓
           Chief Analyst AI
       三级回退 → 纯规则加权
                    ↓
          Redis + SQLite 持久化
                    ↓
       FastAPI (仪表盘 + REST 端点)
```

## 核心链路

| 层级 | 说明 |
|------|------|
| **Macro** | 拉取 5 大指数（上证/深证/创业板/科创50/沪深300）→ 计算 RAI |
| **Signal** | 监听 K 线 → MA/MACD/RSI/背离检测 |
| **Trace** | 成交量突增 + 价量背离 + 突破检测（替代被 WAF 拦截的资金流向） |
| **Risk** | 硬编码风控，一票否决权 |
| **Chief** | 汇总 → LLM 三级回退链 → 证据链输出 |

---

## 快速启动 (NAS)

```bash
cd <your-project-path>
git clone <your-repo-url> .
cp env.example env
vi env   # 填入各 AI 模型的 API Key
```

在 NAS Docker UI → 项目 → 新建 → 选择此目录 → 启动。

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 可视化仪表盘 |
| GET | `/health` | 系统健康 (Redis+DB+Agent+LLM) |
| GET | `/status` | 状态概览 (决策统计+案例统计) |
| GET | `/reports/{agent}` | 指定 Agent 报告 (分页) |
| GET | `/reports/{agent}/latest` | 最新报告 |
| GET | `/decisions` | 决策历史 (分页+统计) |
| GET | `/decisions/{id}` | 决策详情 (含证据链) |

---

## 部署架构

```
NAS 宿主机
├── host 网络模式 (共享 NAS 网卡)
├── 复用 NAS 自带 Redis
├── 代理管理规则
└── 单容器, 内存 ≤ 1GB
```

## 已知限制

东方财富 WAF 拦截实时行情接口。系统已适配：
- 宏观数据改用历史指数接口
- Trace Agent 改用成交量异动分析（替代资金流向）
- K 线数据可用腾讯/新浪备选源

## 环境变量 (env)

| 变量 | 说明 |
|------|------|
| `PRIMARY_AI_API_KEY` | 主力 AI 模型 Key |
| `SECONDARY_AI_API_KEY` | 备用 AI 模型 Key |
| `TERTIARY_AI_API_KEY` | 三级备选 AI 模型 Key |
| `TUSHARE_TOKEN` | (可选) 备用数据源 Token |

# Market Trace V6.0

A/B 股量化分析系统 — 多 Agent 协作 + AI 多级回退链

**测试**: 146 passed ✅ | **Python**: 3.11+ | **部署**: Docker Compose | **端口**: 19377

---

## 仪表盘

打开浏览器访问：

```
http://10.10.10.130:19377
```

暗色交易面板风格，实时显示 RAI 风险偏好指数、5 个 Agent 运行状态、LLM 三级链、最新决策。每 30 秒自动刷新。

---

## 架构

```
[AkShare 数据适配器 (东财历史+腾讯+新浪)]
                    ↓
         NAS Redis (localhost:6379)
                    ↓
┌──────────┬───────────┬──────────┬──────────┐
│ Macro    │ Signal    │ Trace    │ Risk     │
│ (RAI)    │ (MA/MACD) │ (量价异动) │ (否决权)  │
└────┬─────┴─────┬─────┴────┬─────┴────┬─────┘
     └───────────┴──────────┴──────────┘
                    ↓
           Chief Analyst AI
   DeepSeek → Gemini → MiniMax → 纯规则加权
                    ↓
          Redis decision:final + SQLite 持久化
                    ↓
       FastAPI (仪表盘 + 7 REST 端点)
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
cd /volume1/docker/market-trace-v6
git clone https://github.com/mygaga2024/market-trace-v6.git .
cp env.example env
vi env   # 填入 DeepSeek/Gemini/MiniMax 的 Key
```

在绿联 Docker UI → 项目 → 新建 → 选择此目录 → 启动。

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
绿联 NAS (10.10.10.130)
├── host 网络模式 (共享 NAS 网卡)
├── 复用 NAS 自带 Redis (localhost:6379)
├── Sub-Store 管理代理规则
└── 单容器, 内存 ≤ 1GB
```

## 已知限制

东方财富 WAF 拦截实时行情接口 (`/api/qt/clist/get` 路径)。系统已适配：
- 宏观数据改用 `stock_zh_index_daily`（历史指数，正常工作）
- Trace Agent 改用成交量异动分析（替代资金流向）
- K 线数据可用腾讯/新浪备选源

---

## 文档

| 文件 | 内容 |
|------|------|
| `docs/RULES.md` | 编码规范与开发规则 |
| `docs/NOTES.md` | 已知问题与踩坑记录 |
| `docs/OPS.md` | 运维部署手册 |

## 环境变量 (env)

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 主力 AI 模型 |
| `GEMINI_API_KEY` | 备用 AI 模型 |
| `MINIMAX_API_KEY` | 三级备用 AI 模型 |
| `TUSHARE_TOKEN` | (可选) 备用数据源 |

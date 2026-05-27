# Market Trace V6.0 — 运维部署手册

## 架构概览

```
NAS 宿主机 (10.10.10.130)
│
├── Redis (系统自带, localhost:6379)
│
└── Docker 容器 mt6-app (host 网络模式)
    ├── 端口: 19377
    ├── 5 Agent 后台运行
    └── FastAPI + SQLite
```

## 快速启动

```bash
cd /volume1/docker/market-trace-v6
git clone https://github.com/mygaga2024/market-trace-v6.git .
cp env.example env
vi env   # 填入 API Key
```

在**绿联 Docker UI → 项目 → 新建 → 选此目录 → 启动**。

## 仪表盘

```
浏览器打开: http://10.10.10.130:19377
```

实时显示 RAI、Agent 状态、LLM 链、最新决策，30 秒自动刷新。

## 日常运维

### 健康检查
```bash
curl http://10.10.10.130:19377/health
```

### 查看日志
```bash
ssh nas "docker logs mt6-app --tail 50 -f"
```

### 重启
绿联 Docker UI → 项目 → market-trace-v6 → 重启

### 更新代码 (Mac → NAS)
```bash
cd /Users/huangxixi/project/market_trace_v6
tar czf /tmp/mt6.tar.gz --exclude='.git' --exclude='env' --exclude='logs' .
cat /tmp/mt6.tar.gz | ssh nas "cd /volume1/docker/market-trace-v6 && tar xzf -"
# 然后在绿联 UI 中重启项目
```

### 单文件更新 (Mac → NAS)
```bash
cat main.py | ssh nas "cat > /volume1/docker/market-trace-v6/main.py"
# 绿联 UI 点重启
```

## API 端点

```bash
curl http://10.10.10.130:19377/              # 仪表盘 HTML
curl http://10.10.10.130:19377/health        # 健康检查
curl http://10.10.10.130:19377/status        # 状态概览
curl http://10.10.10.130:19377/reports/macro/latest  # 最新宏观
curl http://10.10.10.130:19377/decisions     # 决策历史
```

## Docker 命令

```bash
# 进入容器
ssh nas "docker exec -it mt6-app sh"

# 查看状态
ssh nas "docker ps --filter name=mt6"

# CLI 重建（非 UI）
ssh nas "cd /volume1/docker/market-trace-v6 && docker compose down && docker compose up -d --build"
```

## Agent 监控

| Agent | 心跳 key | 频道 |
|-------|---------|------|
| macro | `agent:heartbeat:macro` | `events:data` → `reports:macro` |
| signal | `agent:heartbeat:signal` | `events:data` → `reports:signal` |
| trace | `agent:heartbeat:trace` | `events:data` → `reports:trace` |
| risk | `agent:heartbeat:risk` | `reports:*` → `risk:override` |
| chief | `agent:heartbeat:chief` | `reports:*` + `risk:override` → `decision:final` |

## LLM 回退链

```
DeepSeek (主力) → Gemini (备用) → MiniMax (三级) → 纯规则 (终极)
```

熔断：连续 3 次失败 → OPEN 60s → HALF_OPEN → 恢复/继续熔断

## 数据源

| 端点 | 状态 | 用途 |
|------|------|------|
| `stock_zh_index_daily` | ✅ | Macro Agent (5大指数) |
| `stock_zh_a_hist` | ✅ | Signal Agent (K线) |
| `stock_zh_a_hist_tx` | ✅ | 腾讯备选 K 线 |
| `stock_zh_a_daily` | ✅ | 新浪备选 K 线 |
| `stock_zh_a_spot_em` | ❌ WAF | 东财实时行情(已降级) |
| `stock_individual_fund_flow` | ❌ WAF | 资金流向(已用成交量替代) |

## 本地开发

```bash
pip install -r requirements.txt
pytest tests/ -q          # 146 tests
python main.py            # 需本地 Redis
curl http://localhost:19377/health
```

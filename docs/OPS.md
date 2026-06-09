# Market Trace V6.0 — 运维部署手册

## 架构概览

```
绿联 NAS GGUG (10.10.10.130)
│
├── Redis (系统自带)
│
└── Docker 容器 mt6-app (host 网络模式)
    ├── 端口: 19377
    ├── 5 Agent 后台运行
    ├── FastAPI + SQLite
    ├── api/   — 路由模块 (health, reports, analyze, backtest, risk, kline)
    ├── services/ — 业务逻辑 (analyzer, prefetch)
    └── volumes:
        ├── ./config/settings.yaml:ro
        ├── ./static (静态文件热更新)
        ├── ./logs
        └── ./data (SQLite 数据库持久化)
```

路由访问共享状态统一通过 `request.app.state`，lifespan 中初始化全部组件。

## 快速启动

```bash
cd <your-project-path>
git clone <your-repo-url> .
cp env.example env
vi env   # 填入 API Key
```

在 **绿联 NAS Docker UI** 中新建项目，指向 `/volume1/docker/market-trace-v6`。

## 仪表盘

```
浏览器打开: http://<your-nas-ip>:19377
```

实时显示 RAI、Agent 状态、LLM 链、最新决策，30 秒自动刷新。

## 日常运维

### 健康检查
```bash
curl http://<your-nas-ip>:19377/health
```

### 查看日志
```bash
ssh <user>@<nas-ip> -p <port> "docker logs mt6-app --tail 50 -f"
```

### 重启
NAS Docker UI → 项目 → market-trace-v6 → 重启

### SSH 连接
```bash
# 已配置密钥免密登录
ssh nas
# 或手动指定:
ssh -p 16011 -i ~/.ssh/id_ed25519_nas mygaga@10.10.10.130
```

### 更新代码 (本地 → NAS)
```bash
cd /Users/huangxixi/project/market_trace_v6
tar czf /tmp/mt6.tar.gz --exclude='.git' --exclude='env' --exclude='logs' --exclude='.pytest_cache' --exclude='data' .
cat /tmp/mt6.tar.gz | ssh nas "cd /volume1/docker/market-trace-v6 && docker compose down; tar xzf - && docker compose up -d --build"
```

> 仅修改静态文件 (JS/CSS) 时无需重建，直接 scp 即可：
> ```bash
> scp -P 16011 static/js/dashboard.js nas:/volume1/docker/market-trace-v6/static/js/
> ssh nas "docker compose restart"  # 无需 --build
> ```
> 若出现 `PermissionError: /app/logs/`，执行: `ssh nas "docker run --rm --user root -v /volume1/docker/market-trace-v6/data:/data alpine chown -R 1000:1000 /data"`

## API 端点

```bash
curl http://<your-nas-ip>:19377/                       # 仪表盘 HTML
curl http://<your-nas-ip>:19377/health                  # 健康检查
curl http://<your-nas-ip>:19377/status                  # 状态概览
curl http://<your-nas-ip>:19377/reports/macro/latest    # 最新宏观
curl http://<your-nas-ip>:19377/decisions                # 决策历史
```

## Docker 命令

```bash
# 进入容器
ssh <user>@<nas-ip> -p <port> "docker exec -it mt6-app sh"

# 查看状态
ssh <user>@<nas-ip> -p <port> "docker ps --filter name=mt6"

# CLI 重建（非 UI）
ssh <user>@<nas-ip> -p <port> "cd <project-path> && docker compose down && docker compose up -d --build"
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
主力模型 → 备用模型 → 三级模型 → 纯规则 (终极)
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
| `hq.sinajs.cn` | ✅ | 股票名称/实时行情 fallback |

## 本地开发

```bash
pip install -r requirements.txt
pytest tests/ -q          # 170 tests
python main.py            # 需本地 Redis
curl http://localhost:19377/health
```

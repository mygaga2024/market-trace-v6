# Market Trace V6.0 — 运维部署手册

## 快速启动（NAS）

```bash
# 首次部署
cd /volume1/docker/market-trace-v6
git clone https://github.com/mygaga2024/market-trace-v6.git .
cp env.example env
vi env   # 填入 API Key
# 在绿联 Docker UI → 项目 → 新建 → 选此目录 → 启动
```

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
在绿联 Docker UI → 项目 → market-trace-v6 → 重启

### 更新代码
```bash
# Mac 本地
cd /Users/huangxixi/project/market_trace_v6
git pull   # 或本地修改后 git push

# 推送到 NAS（Mac → NAS）
cat main.py | ssh nas "cat > /volume1/docker/market-trace-v6/main.py"
cat docker-compose.yml | ssh nas "cat > /volume1/docker/market-trace-v6/docker-compose.yml"
# 然后在绿联 UI 中重启项目
```

## API 端点

```bash
curl http://10.10.10.130:19377/health        # 健康检查
curl http://10.10.10.130:19377/status        # 状态概览
curl http://10.10.10.130:19377/reports/macro # 宏观报告列表
curl http://10.10.10.130:19377/reports/macro/latest  # 最新宏观报告
curl http://10.10.10.130:19377/decisions     # 决策历史
curl http://10.10.10.130:19377/decisions/d1  # 指定决策详情
```

## Docker 命令

```bash
# 进入容器
ssh nas "docker exec -it mt6-app sh"

# 查看容器状态
ssh nas "docker ps --filter name=mt6"

# 手动重启（非 UI）
ssh nas "cd /volume1/docker/market-trace-v6 && docker compose down && docker compose up -d"
```

## Agent 监控

| Agent | 心跳 key | 频道 |
|-------|---------|------|
| macro | `agent:heartbeat:macro` | `events:data` |
| signal | `agent:heartbeat:signal` | `events:data` |
| trace | `agent:heartbeat:trace` | `events:data` |
| risk | `agent:heartbeat:risk` | `reports:*` |
| chief | `agent:heartbeat:chief` | `reports:*` + `risk:override` |

## LLM 回退链状态

```
DeepSeek (主力) → Gemini (备用) → MiniMax (三级) → 纯规则 (终极)
```

熔断：连续 3 次失败 → OPEN 60s → HALF_OPEN → 恢复/继续熔断

## 本地开发

```bash
# Mac 本地测试
pip install -r requirements.txt
pytest tests/ -q

# 本地运行（需本地 Redis）
redis-server &
python main.py
curl http://localhost:8000/health
```

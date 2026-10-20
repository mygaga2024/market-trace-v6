# Market Trace V6 · Go Edition

A/B 股实时行情、技术分析、风险控制与决策记录的 Go Web 控制台。界面采用深松绿色侧栏与浅灰工作面，按新版授权中心面板重新设计。

**版本**: 2.0.0 · **Go**: 1.23+ · **端口**: 19377 · **部署**: 单二进制 / Docker

## 快速启动

```bash
go run ./cmd/mt6
```

打开 `http://localhost:19377`。首次启动会在 `data/go/state.json` 写入默认自选股、策略开关和风控参数。

常用环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `19377` | HTTP 监听端口 |
| `MT6_ADDRESS` | `0.0.0.0:19377` | 完整监听地址，设置后覆盖 `PORT` |
| `MT6_DATA_DIR` | `data/go` | 持久化目录 |
| `API_TOKEN` | 空 | 设置后保护 API；占位符 `your-*` 视为未配置 |
| `MT6_HTTPS` | `false` | 登录 Cookie 是否使用 Secure |
| `MT6_REQUEST_TIMEOUT` | `12s` | 行情与诊股请求超时 |

## 功能

- 真实 A 股行情：东方财富指数与自选股报价
- 智能诊股：MA、RSI、MACD、KDJ、ATR、布林带、量比和支撑阻力
- 可解释决策：多空信号、评分、动作、置信度和风险等级
- 风控配置：单票上限、止损、单日亏损、最低置信度
- 自选与审计：JSON 原子持久化，增删、策略和风控操作可追溯
- 响应式界面：桌面双栏、移动端侧栏抽屉、自选名单和诊股走势图
- 可选登录：Bearer Token 或 HttpOnly 会话 Cookie

## 架构

```text
cmd/mt6                 Go 服务入口
internal/config         环境配置
internal/market         Eastmoney 行情、指标计算、决策与缓存
internal/store          自选/决策/审计/风控 JSON 持久化
internal/server         net/http 路由、鉴权和 API
web                     内嵌 HTML/CSS/JS 前端资源
```

行情与 K 线来自东方财富公开接口。数据不可用时返回显式降级状态，不用模拟价格或兜底指标参与评分。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 服务与行情健康状态 |
| `GET` | `/api/v1/dashboard` | 控制台聚合数据 |
| `GET` | `/api/v1/stocks` | 自选股与实时行情 |
| `POST` | `/api/v1/stocks` | 添加自选股 |
| `DELETE` | `/api/v1/stocks/{symbol}` | 移除自选股 |
| `POST` | `/api/v1/analyze` | 按股票代码生成量化决策 |
| `GET` | `/api/v1/decisions` | 决策历史 |
| `GET` | `/api/v1/audit` | 审计事件 |
| `GET/PUT` | `/api/v1/settings` | 读取/更新风控参数 |
| `POST` | `/api/v1/strategies/{key}/toggle` | 启用/停用策略 |

## 测试与部署

```bash
go test ./...
go test -race ./...
python3 -m pytest tests/ -v
```

```bash
docker compose up -d --build app
curl -s localhost:19377/health
```

Docker 镜像使用多阶段构建，最终运行层只包含静态 Go 二进制、CA 证书和时区数据。Web 资源通过 `go:embed` 打入二进制。

## Python 版本

原有 FastAPI + Agent 实现继续保留在仓库中，方便回滚和结果对照：

```bash
python3 main.py
docker build -f Dockerfile.python -t market-trace-v6-python .
```

默认 `Dockerfile` 和生产 Compose 已切换到 Go 版本。

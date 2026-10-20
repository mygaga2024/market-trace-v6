# Market Trace V6 · Go Edition

A/B 股实时行情、量化分析、用户权限、交易执行与托管交易的 Go Web 控制台。界面采用深松绿色侧栏与浅灰工作面，按新版授权中心面板重新设计。

**版本**: 2.1.0 · **Go**: 1.23+ · **端口**: 19377 · **部署**: 单二进制 / Docker

## 快速启动

```bash
go run ./cmd/mt6
```

打开 `http://localhost:19377`，首次访问会进入注册页。第一个账户自动成为管理员。

常用环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `19377` | HTTP 监听端口 |
| `MT6_ADDRESS` | `0.0.0.0:19377` | 完整监听地址，设置后覆盖 `PORT` |
| `MT6_DATA_DIR` | `data/go` | 持久化目录 |
| `SESSION_TTL` | `168h` | 登录会话有效期 |
| `ALLOW_REGISTRATION` | `true` | 是否允许后续公开注册 |
| `API_TOKEN` | 空 | 可选的自动化 Bearer Token；占位符 `your-*` 视为未配置 |
| `MT6_HTTPS` | `false` | 登录 Cookie 是否使用 Secure |
| `TRADING_MODE` | `paper` | `paper` 模拟盘，`live` 官方券商网关 |
| `ALLOW_LIVE_TRADING` | `false` | 实盘总开关，必须显式开启 |
| `ALLOW_LIVE_CUSTODY` | `false` | 实盘托管二次开关 |

## 账户与登录

- 本地账户密码使用 Argon2id 加盐哈希，正文与日志中不保存明文。
- 登录成功后使用 `HttpOnly`、`SameSite=Strict` 会话 Cookie。
- 管理员可在“用户管理”中开关其他账户的交易权限。
- 系统设置页支持修改密码；扫码创建的账户可设置本地备用密码。
- 可选扫码登录只接官方 OAuth/OIDC。未配置同花顺等平台的官方凭据时，扫码入口会明确禁用，不调用非官方接口。

扫码登录所需变量见 `env.example` 的 `QR_LOGIN_*` 段。

## 交易与托管

应用内置一个默认 100 万元资金的模拟券商账户，可在“交易终端”进行买入、卖出、限价委托、撤单和持仓估值。模拟成交会计算佣金和卖出印花税。

实盘能力通过登录后的官方券商网关执行：

```text
Market Trace (NAS)
        │ HTTPS + HMAC-SHA256
        ▼
Official Broker Gateway
        │ 券商官方 SDK / 授权通道
        ▼
Broker / Account
```

启用实盘需要同时满足：

1. `TRADING_MODE=live`
2. `ALLOW_LIVE_TRADING=true`
3. 配置 `BROKER_GATEWAY_URL`、`BROKER_GATEWAY_KEY_ID`、`BROKER_GATEWAY_SECRET`、`BROKER_ACCOUNT_ID`
4. 托管交易还需 `ALLOW_LIVE_CUSTODY=true`，并在界面输入 `ENABLE CUSTODY` 二次确认

网关签名协议和接口约定见 [BROKER_GATEWAY.md](BROKER_GATEWAY.md)。没有官方网关、券商授权和账户凭据时，服务会安全降级为模拟盘，绝不伪造实盘成交。

托管引擎仅使用评分、置信度、单次金额上限和可用持仓做确定性判断；限制在 A 股连续竞价时段，同一股票同方向每日最多执行一次。启用实盘托管前必须自行完成券商风控、合规和资金上限评估。

## 行情与分析

- 东方财富实时指数与自选股报价。
- 东方财富前复权日 K，失败时自动降级腾讯前复权 K 线。
- MA、RSI、MACD、KDJ、ATR、布林带、量比、支撑阻力。
- 可解释评分、动作、置信度与风险等级。
- 数据不可用时显式降级，不使用模拟价格参与评分。

## 架构

```text
cmd/mt6                 Go 服务入口
internal/auth           Argon2id、会话、限流、官方 OAuth/OIDC
internal/config         环境配置
internal/market         行情、K 线降级、指标计算与决策
internal/store          用户、自选、决策、审计、交易 JSON 持久化
internal/trading        模拟券商、官方网关客户端、托管引擎
internal/server         net/http 路由、鉴权和 API
web                     内嵌 HTML/CSS/JS 前端资源
```

状态文件使用临时文件 + `fsync` + 原子替换写入，权限为 `0600`。

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 服务与行情健康状态 |
| `POST` | `/api/v1/auth/register` | 注册本地账户 |
| `POST` | `/api/v1/auth/login` | 登录 |
| `POST` | `/api/v1/auth/logout` | 退出登录 |
| `POST` | `/api/v1/auth/password` | 修改密码 |
| `GET` | `/api/v1/auth/status` | 登录/注册/扫码配置状态 |
| `GET` | `/api/v1/auth/qr/start` | 生成官方扫码授权地址 |
| `GET` | `/api/v1/dashboard` | 控制台聚合数据 |
| `GET/POST` | `/api/v1/trading/orders` | 查询/提交委托 |
| `POST` | `/api/v1/trading/orders/{id}/cancel` | 撤单 |
| `GET` | `/api/v1/trading/account` | 账户与持仓 |
| `GET/PUT` | `/api/v1/custody` | 托管参数 |
| `POST` | `/api/v1/custody/run` | 手动执行一次托管检查 |
| `GET` | `/api/v1/users` | 用户列表（管理员） |
| `POST` | `/api/v1/users/{id}/trading` | 设置交易权限（管理员） |

完整行情、自选、审计和风控端点参见 `internal/server/server.go`。

## 测试与 Docker

```bash
go test ./...
go test -race ./...
go vet ./...
python3 -m pytest tests/ -v
```

```bash
docker compose up -d --build app
curl -s localhost:19377/health
```

Docker 使用多阶段构建，最终运行层只包含静态 Go 二进制、CA 证书和时区数据。Web 资源通过 `go:embed` 打入二进制。

## Python 版本

原有 FastAPI + Agent 实现继续保留，用于回滚和结果对照：

```bash
python3 main.py
docker build -f Dockerfile.python -t market-trace-v6-python .
```

# Market Trace V6.0 — 已知问题与注意事项

## 当前问题

### 1. 东方财富 WAF 拦截 ✅ 已适配

**状态**：已适配  
**影响**：`/api/qt/clist/get` 路径被东财 CDN 主动断开（非代理/网络问题）

`push2.eastmoney.com` 根路径正常（404），API 路径带参请求被断开。
NAS 原生 curl 也失败，东财 WAF 层面的反爬。

**适配方案**：
| 原接口 | 状态 | 替代方案 |
|--------|------|----------|
| `stock_zh_index_spot_em` | ❌ | `stock_zh_index_daily` (5大指数历史数据) |
| `stock_board_concept_name_em` | ❌ | 板块数据降权，RAI 纯用指数 |
| `stock_individual_fund_flow` | ❌ | Trace Agent 改用成交量异动分析 |
| `stock_zh_a_spot_em` | ❌ | K线用 `stock_zh_a_hist` + 腾讯/新浪备选 |

**后续方案**：
- 对接 Tushare token 认证接口（不受 WAF 限制）
- 框架已预留数据源接口，settings.yaml 配置即可切换

### 2. 网络架构演变

| 版本 | 方式 | 结果 |
|------|------|------|
| v1 | Docker bridge + proxy | Redis 隔离，代理拒东财 |
| v2 | host 网络 + proxy | Redis 端口冲突，代理仍拒 |
| **v3** | **host 网络 + NAS Redis + 代理规则** | ✅ 生产运行 |

当前：
- 复用 NAS 自带 Redis，不在 docker-compose 中启动 Redis 容器
- Docker 容器用 `network_mode: host` 共享 NAS 网卡
- 代理软件管理规则，东财设为 DIRECT

### 3. NAS 文件系统

- `.` 前缀文件会被隐藏：`.env` → `env`
- docker-compose 显式指定 `env_file: ./env`
- rsync 不支持 NAS 路径，改用 `tar | ssh` 管道

### 4. Docker Compose 文件

- 文件名：`docker-compose.yaml`
- 已移除 `docker-compose.yml` 避免双文件冲突
- `version: "3.8"` 过时警告无害（Docker Engine 兼容）

### 5. 数据供应商状态

| 供应商 | 接口 | 速率限制 | 用途 |
|--------|------|---------|------|
| AkShare | `stock_zh_index_daily` | 无限制 | ✅ Macro Agent (5大指数) |
| AkShare | `stock_zh_a_hist` | 无限制 | ✅ Signal Agent (K线) |
| AkShare | `stock_zh_a_hist_tx` | 无限制 | ✅ 腾讯备选 K线 |
| AkShare | `stock_zh_a_daily` | 无限制 | ✅ 新浪备选 K线 |
| AkShare | `stock_zh_a_spot_em` | ❌ WAF | 东财实时行情(已降级) |
| AkShare | `stock_individual_fund_flow` | ❌ WAF | 资金流向(已用成交量替代) |
| **Tushare** | **`daily`** | **200次/分** | **✅ 实时+K线 (已启用)** |
| Tushare | `moneyflow` | 1次/小时 | ❌ 资金流向(频率限制不可用) |
| Tushare | `index_daily` | 1次/分 | ⚠️ 宏观(需延迟,备选) |
| XTick | — | 预留 | ⬜ 待对接 |
| Yquoter | — | 预留 | ⬜ 待对接 |

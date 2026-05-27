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
| **v3** | **host 网络 + NAS Redis + SubStore 规则** | ✅ 生产运行 |

当前：
- 复用 NAS 自带 Redis (`localhost:6379`)，不在 docker-compose 中启动 Redis 容器
- Docker 容器用 `network_mode: host` 共享 NAS 网卡
- Sub-Store (`http://10.10.10.130:53001`) 管理代理规则，东财设为 DIRECT

### 3. 绿联 NAS 文件系统

- `.` 前缀文件会被隐藏：`.env` → `env`
- docker-compose 显式指定 `env_file: ./env`
- rsync 不支持 NAS 路径，改用 `tar | ssh` 管道
- 绿联 UI 自动生成 `docker-compose.yaml` → 我们直接用它作为主文件

### 4. Docker Compose 文件

- 文件名：`docker-compose.yaml`（绿联 UI 更短）
- 已移除 `docker-compose.yml` 避免双文件冲突
- `version: "3.8"` 过时警告无害（Docker Engine 兼容）

### 5. 数据提供者供应商路线图

| 供应商 | 状态 | 接入方式 |
|--------|------|----------|
| AkShare (东财历史) | ✅ 生产 | `stock_zh_index_daily` |
| AkShare (腾讯) | ✅ 备选 | `stock_zh_a_hist_tx` |
| AkShare (新浪) | ✅ 备选 | `stock_zh_a_daily` |
| XTick | ⬜ 预留 | 接口已定义，待对接 |
| Yquoter | ⬜ 预留 | 接口已定义，待对接 |
| Tushare | ⬜ 预留 | `settings.yaml` 配置 token |
| FinQ4Cn-mcp | ⬜ 预留 | 接口已定义，待对接 |

## 环境速查

| 组件 | 地址/配置 |
|------|-----------|
| 仪表盘 | `http://10.10.10.130:19377` |
| NAS SSH | `ssh mygaga@10.10.10.130 -p 16011` |
| 健康检查 | `http://10.10.10.130:19377/health` |
| Sub-Store | `http://10.10.10.130:53001` |
| Mihomo 面板 | `http://10.10.10.137:9090/ui` |
| GitHub | `github.com/mygaga2024/market-trace-v6` |
| NAS 项目路径 | `/volume1/docker/market-trace-v6/` |

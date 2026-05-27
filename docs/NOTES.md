# Market Trace V6.0 — 已知问题与注意事项

## 当前问题

### 1. 代理拒连 eastmoney（反爬）

**状态**：未解决  
**影响**：Macro Agent 无法拉取真实宏观数据，RAI 固定 0.50 中性

```
代理: 10.10.10.137:7890
症状: 通 httpbin/baidu，拒 *.push2.eastmoney.com
根因: 东方财富检测代理 IP 并断开 HTTPS CONNECT
```

**排查记录**：
- DNS 解析正常 ✅
- 根路径 `https://push2.eastmoney.com` 返回 404 ✅
- API 路径带参数 → ProxyError ❌
- 非代理直连 → RemoteDisconnected ❌（容器无公网）

**解决方向**：
1. 代理端添加 IP 轮换或延迟
2. 更换代理（SOCKS5/透明代理）
3. 改用 Tushare Pro（付费，支持 token 认证）
4. 在宿主机跑数据抓取，推送到 Redis

### 2. 绿联 NAS 文件系统

- `.` 前缀文件会被隐藏：`.env` → 改为 `env`，`.env.example` → `env.example`
- docker-compose 中显式指定 `env_file: ./env`
- rsync 不支持 NAS 路径，改用 `tar | ssh` 管道传输

### 3. Docker 权限

- 绿联 NAS 上 docker 创建的目录属于 root，mygaga 无权修改
- 解决：`.dockerignore` 排除 data/，或预创建目录
- 当前容器以 root 运行（兼容性折衷）

### 4. 双 compose 文件冲突

- 绿联 UI 会生成 `docker-compose.yaml`
- 我们的文件是 `docker-compose.yml`
- 解决方案：`docker-compose.yaml` 加入 `.gitignore` 并删除

## 环境速查

| 组件 | 地址/配置 |
|------|-----------|
| NAS SSH | `ssh mygaga@10.10.10.130 -p 16011` |
| 健康检查 | `http://10.10.10.130:19377/health` |
| 代理 | `http://10.10.10.137:7890` |
| GitHub | `github.com/mygaga2024/market-trace-v6` |
| NAS 项目路径 | `/volume1/docker/market-trace-v6/` |

## 配置密钥位置

| 文件 | 说明 |
|------|------|
| `env` | 实际 API Key（nas 本地，不入 git） |
| `env.example` | 模板（github，占位符） |
| `config/settings.yaml` | 全配置（`${VAR}` 引用 env） |

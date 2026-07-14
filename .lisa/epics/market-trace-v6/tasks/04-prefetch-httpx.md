# Task 4: prefetch 迁移到 httpx

## Status: done

## Goal
将 `services/prefetch.py` 中 `_fetch_name_via_sina` 和 `fetch_stock_price_via_sina` 的同步 `requests.get` 调用替换为 `httpx.AsyncClient`，消除同步阻塞。

## Files
- `services/prefetch.py` — 修改 `_fetch_name_via_sina`、`fetch_stock_price_via_sina`、`fetch_stock_price_tencent`

## Steps
1. 在 `services/prefetch.py` 模块级创建复用的 `httpx.AsyncClient`（类似 `_get_tencent_client`）
2. 将 `_fetch_name_via_sina` 改为 async 直接使用 httpx
3. 将 `fetch_stock_price_via_sina` 改为 async 直接使用 httpx
4. 将 `fetch_stock_price_tencent` 改为 async 直接使用 httpx
5. 确保调用方不依赖 `asyncio.to_thread` 的同步包装
6. 运行 `pytest tests/ -v` 全验证

## Done When
- [ ] `services/prefetch.py` 中无 `requests.get` 调用
- [ ] 所有 Sina/腾讯 接口使用 httpx AsyncClient
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署后持仓列表实时价格正常显示

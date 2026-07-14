# Task 2: Scanner 并发优化

## Status: done

## Goal
修复 `services/scanner.py` 的 `smart_scan` 对全市场 5000+ 股票同时 `create_task` 导致的资源耗尽问题，改成分批并发（每批 200 只）。

## Files
- `services/scanner.py` — 修改 `smart_scan` 和 `quick_scan` 函数

## Steps
1. 在 `smart_scan` (line ~325) 中，将 `asyncio.gather(*tasks)` 改为分批执行
2. 每批 200 只，批内 sem=10，批次间有短暂间隔
3. 同样修改 `quick_scan` 中的深度检查部分 (line ~235)
4. 添加进度日志（每完成一批输出一次）
5. 运行 `pytest tests/ -v -k scanner` 确保不引入新错误

## Done When
- [ ] `smart_scan` 不再对 5000+ 股票同时 create_task
- [ ] 分批大小 200，内部并发度 10
- [ ] 有进度日志输出
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署验证 ok
- [ ] 全市场扫描功能正常（调用 `/scan/smart` 验证）

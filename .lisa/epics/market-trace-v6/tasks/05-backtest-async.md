# Task 5: 回测异步化

## Status: done

## Goal
将 `GET /backtest/summary` 从同步阻塞调用改为后台异步执行，避免请求超时。使用 `asyncio.to_thread` 包装回测函数。

## Files
- `api/backtest.py` — 修改 `backtest_summary` 和 `backtest_run` 端点

## Steps
1. 将 `api/backtest.py` 中 `run_strategy_backtest` 调用包装在 `asyncio.to_thread()` 中
2. 同样处理 `backtest_run` 端点的 `run_strategy_backtest` 调用
3. 确保回测结果仍通过 JSON 正确返回
4. 运行 `pytest tests/ -v -k backtest` 验证

## Done When
- [ ] `GET /backtest/summary` 不再阻塞事件循环
- [ ] `POST /backtest/run` 不再阻塞事件循环
- [ ] 回测结果格式与之前一致
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署后调用 `/backtest/summary` 正常返回

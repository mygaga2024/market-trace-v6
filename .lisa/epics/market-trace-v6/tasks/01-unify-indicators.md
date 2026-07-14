# Task 1: 统一技术指标计算

## Status: done

## Goal
消除 `_calc_macd`/`_calc_rsi`/`_calc_atr` 在 `services/analyzer.py`、`agents/signal_agent.py`、`backtest/strategy_backtest.py` 三处的重复实现，统一切到 `core/strategies.py`。

## Files
- `core/strategies.py` — 添加统一的 `_calc_macd_vec()` 函数，保留现有 `_calc_rsi`, `_calc_atr`
- `services/analyzer.py` — 删除本地 `_calc_macd`/`_calc_rsi`，改为 `from core.strategies import _calc_rsi, _calc_atr, _calc_macd_vec`
- `agents/signal_agent.py` — 删除本地 `_calc_macd`/`_calc_rsi`，改为 import
- `backtest/strategy_backtest.py` — 删除本地 `_calc_rsi`/`_calc_atr`，改为 import

## Steps
1. 在 `core/strategies.py` 中添加 `_calc_macd_vec()` 函数（返回 `{"dif": ..., "dea": ..., "histogram": ...}` 的 dict，兼容 analyzer 的调用方式）
2. 确认 strategies.py 中已有的 `_calc_rsi` 和 `_calc_atr` 接受 np.ndarray 参数
3. 修改 `services/analyzer.py`: 删除 `_calc_macd`、`_calc_rsi` 定义，改为 import
4. 修改 `agents/signal_agent.py`: 删除 `_calc_macd`、`_calc_rsi` 定义，改为 import（注意 signal_agent 的 macd 返回 np.ndarray，需适配）
5. 修改 `backtest/strategy_backtest.py`: 删除 `_calc_rsi`、`_calc_atr` 定义，改为 import
6. 运行 `pytest tests/ -v` 确保全部通过

## Done When
- [ ] `_calc_macd`/`_calc_rsi`/`_calc_atr` 只在 `core/strategies.py` 中定义
- [ ] `services/analyzer.py` 不再有重复实现
- [ ] `agents/signal_agent.py` 不再有重复实现
- [ ] `backtest/strategy_backtest.py` 不再有重复实现
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署验证 ok

# Task 7: Scanner 粗筛去重

## Status: done

## Goal
消除 `api/analyze.py` 和 `services/scanner.py` 中重复的粗筛逻辑（各策略的 change_pct 阈值条件）。

## Files
- `core/strategies.py` — 为每个策略添加 `rough_threshold` 字段
- `api/analyze.py` — 删除硬编码的粗筛，改为从 STRATEGIES 读取
- `services/scanner.py` — 删除硬编码的粗筛，改为从 STRATEGIES 读取

## Steps
1. 在 `core/strategies.py` 的 STRATEGIES 字典中，为每个策略添加 `rough_threshold` 字典（含 `min_change`, `max_price` 等）
2. 修改 `api/analyze.py` 的 `screen_stocks`，从 STRATEGIES 读取粗筛条件
3. 修改 `services/scanner.py` 的 `quick_scan`，从 STRATEGIES 读取粗筛条件
4. 确保粗筛逻辑与之前等效
5. 运行 `pytest tests/ -v` 全通过

## Done When
- [ ] `api/analyze.py` 中无硬编码粗筛逻辑
- [ ] `services/scanner.py` 中无硬编码粗筛逻辑
- [ ] 粗筛条件统一定义在 `core/strategies.py`
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署后选股/扫描结果与之前一致

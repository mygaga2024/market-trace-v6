# Task 3: 版本号统一至 1.2.0

## Status: done

## Goal
统一所有文件中的版本号为 1.2.0，消除不一致。

## Files
- `main.py` — line 315: `version="1.1.8"` → `"1.2.0"`
- `api/health.py` — line 43: `"version": "1.1.8"` → `"1.2.0"`；line 91 同
- `api/health.py` — line 107: `"version": "1.1.8"` → `"1.2.0"`
- `PROJECT_STATUS.md` — 版本号 1.1.9 → 1.2.0
- `PROGRESS.md` — 如有版本号引用也更新

## Steps
1. 全局搜索 `1.1.8` 和 `1.1.9`，确认所有位置
2. 批量替换为 `1.2.0`
3. 更新 `PROJECT_STATUS.md` 修复记录表，添加本次版本更新记录

## Done When
- [ ] 项目中不存在旧版本号 `1.1.8` 或 `1.1.9` 的硬编码
- [ ] PROJECT_STATUS.md 版本号和修复记录已更新
- [ ] `pytest tests/ -v` 全通过

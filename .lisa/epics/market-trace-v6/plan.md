# Plan: market-trace-v6

## Overview

基于研究评估结果，优先修复 7 个 P1 问题：统一指标计算、Scanner 并发优化、版本号统一、prefetch httpx 迁移、回测异步化、前端拆分、Scanner 粗筛去重。每个任务独立可验证，不破坏现有架构。

## Tasks

1. 统一技术指标计算 — `tasks/01-unify-indicators.md`
2. Scanner 并发优化 — `tasks/02-scanner-concurrency.md`
3. 版本号统一至 1.2.0 — `tasks/03-version-bump.md`
4. prefetch 迁移到 httpx — `tasks/04-prefetch-httpx.md`
5. 回测异步化 — `tasks/05-backtest-async.md`
6. 前端 JS 拆分 — `tasks/06-frontend-split.md`
7. Scanner 粗筛去重 — `tasks/07-scanner-dedup.md`

## Dependencies

- 01: [] (独立，仅依赖 core/strategies.py)
- 02: [] (独立，仅依赖 services/scanner.py)
- 03: [] (独立，全局替换)
- 04: [] (独立，仅依赖 services/prefetch.py)
- 05: [] (独立，仅依赖 api/backtest.py)
- 06: [01, 03, 04, 05] (前端需后端改动先稳定)
- 07: [02] (Scanner 优化后再去重)

## Risks

- 01 统一指标: `_calc_macd` 返回值格式不同（analyzer 返回 dict，signal_agent 返回 np.ndarray），需兼容
- 02 Scanner: 分批后扫描耗时增加，需控制批次大小
- 06 Frontend: 拆分可能引入 JS 加载问题，需保持向后兼容
- 所有改动需 pytest + NAS 部署双验证

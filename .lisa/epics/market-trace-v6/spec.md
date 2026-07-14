# Spec: Market Trace V6 全模块完成度评估与优化

## 目标

对项目所有模块（后端12模块 + 前端WebUI）进行系统性的完成度评估，识别未完工/待优化项，修复至同类产品最佳水平。

## 范围

### 评估范围

| 层级 | 模块 | 文件 |
|------|------|------|
| **后端-核心** | 消息总线 | `core/bus.py` |
| | LLM工厂+回退链 | `core/llm_factory.py` |
| | 策略定义 | `core/strategies.py` |
| | 风控管理 | `core/risk_manager.py` |
| | 熔断器 | `core/circuit_breaker.py` |
| | 仓位计算 | `core/position_sizing.py` |
| | 纸上交易 | `core/paper_trader.py` |
| | 案例记忆 | `core/memory.py` |
| | 通知 | `core/notifier.py` |
| | 数据模型 | `core/schema.py` |
| **后端-服务** | 诊股分析 | `services/analyzer.py` |
| | 数据预加载 | `services/prefetch.py` |
| | 市场扫描 | `services/scanner.py` |
| **后端-API** | 健康检查 | `api/health.py` |
| | 诊股选股 | `api/analyze.py` |
| | 回测 | `api/backtest.py` |
| | 风控 | `api/risk.py` |
| | K线渲染 | `api/kline.py` |
| | 持仓 | `api/watchlist.py` |
| | 安全+限流 | `api/deps.py`, `api/rate_limit.py` |
| **后端-Agent** | 宏观分析师 | `agents/macro_agent.py` |
| | 信号分析师 | `agents/signal_agent.py` |
| | 轨迹Agent | `agents/trace_agent.py` |
| | 风控Agent | `agents/risk_agent.py` |
| | 首席决策 | `agents/chief_analyst.py` |
| **后端-回测** | 回测运行器 | `backtest/runner.py` |
| | 策略回测 | `backtest/strategy_backtest.py` |
| | 策略管理 | `backtest/strategy_manager.py` |
| **后端-数据** | AkShare | `data_provider/akshare_impl.py` |
| | Tushare | `data_provider/tushare_impl.py` |
| | 容错 | `data_provider/fallback_handler.py` |
| **前端** | 仪表盘HTML | `templates/dashboard.html` |
| | JS交互 | `static/js/dashboard.js` |
| | 图表 | `static/js/charts.js` |
| | CSS样式 | `static/css/dashboard.css` |

### 评估维度

对每个模块从以下维度打分（1-5）：

1. **功能完整性** — 核心功能是否全部实现？有无 TODO/FIXME？
2. **健壮性** — 错误处理、边界条件、超时、重试是否到位？
3. **性能** — 有无性能瓶颈？并发、缓存、复用是否合理？
4. **代码质量** — 类型注解、文档、命名、重复代码
5. **前端体验** — UI 交互流畅度、数据渲染正确性、错误状态展示

### 输出物

1. **完成度矩阵** — 每个模块的5维评分 + 汇总
2. **问题清单** — 按优先级(P0/P1/P2/P3)列出所有待修项
3. **修复计划** — 按优先级逐一修复，每个修复后验证

## 验收标准

- [ ] 所有模块完成度评估报告已生成
- [ ] P0/P1 问题全部修复
- [ ] `pytest tests/ -v` 全通过
- [ ] NAS 部署验证通过
- [ ] 前端 Web 实测通过
- [ ] 版本号更新至 1.2.0

## 技术约束

- 不破坏现有模块间依赖和消息总线协议
- 不引入新的外部依赖（除非确有必要）
- 保持向后兼容，现有 API 返回值结构不变

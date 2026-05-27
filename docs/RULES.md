# Market Trace V6.0 — 开发规范

## 编码原则

### 确定性优先
- 传统指标与硬编码风控规则具有最高优先级
- AI 仅作为赔率修正，不替代规则决策
- Risk Agent 拥有最终一票否决权

### 配置驱动
- 所有参数从 `config/settings.yaml` 读取，严禁硬编码
- API Key 通过 `${ENV}` 占位符 → `env` 文件注入
- 数据源通过 `data_providers` 列表动态加载

### 最小干预
- `core/schema.py` 中的 dataclass 字段一经定义不得随意删除
- 公共 API 方法签名（`data_provider/base.py`）禁止变更
- 新增字段只能追加，保持向后兼容

## 代码风格

- Python 3.11+，全异步 asyncio
- 所有 I/O 操作（HTTP、Redis、DB）必须异步
- 流式处理数据，避免一次性加载到内存
- Docker 单容器内存限制 ≤ 1GB

## 修改规则

1. **修改前审查**：`grep` 确认所有调用方和依赖
2. **原子修改**：每次最多改 5 个文件
3. **禁止行为**：
   - 禁止删除既有非废弃注释
   - 禁止使用 `...` `// 省略` 等占位符
   - 禁止输出不完整代码
4. **测试覆盖**：逻辑变更必须至少 1 个边界测试

## 异常处理

- LLM 请求失败 → 多级回退链自动降级
- 数据源不可用 → FallbackHandler 读缓存 → DATA_MISSING 告警
- 熔断器保护所有外部 HTTP 调用
- Agent 异常不中断消息循环（_process_safe 隔离）

## Git 规则

- 每阶段完成后 commit + tag（v0.1 ~ v1.0.0）
- `env` 文件不入库（gitignore）
- `PROGRESS.md` 仅本地
- 绿联 UI 生成的 `docker-compose.yaml` 不入库

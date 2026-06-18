# AGENTS.md — AI 会话规则

## 会话启动

**务必**在每次会话开始时执行 `memory_search_nodes` 搜索近期 session 记录，了解上一会话做了什么：

```
memory_search_nodes(query="session-2025")  # 搜索近期的 session 记录
```

## 会话结束

每次会话结束时**务必**将所做改动记录到 Memory 知识图谱：

1. 创建 `Session` 类型实体，命名格式 `session-YYYY-MM-DD-简要描述`
2. 记录内容：改了什么、为什么改、涉及哪些文件、commit hash、测试结果
3. 同步更新 `LLM Fallback Chain` 实体（如有改动）

## 提交前检查

- 运行相关测试确认通过
- 不提交未完成的代码

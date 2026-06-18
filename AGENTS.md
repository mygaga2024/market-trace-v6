# AGENTS.md — AI 会话规则

## 会话启动

**务必**在每次会话开始时按序执行以下 4 步：

### 1. Memory 历史
```
memory_search_nodes(query="session-")  # 搜索近期的 session 记录
```

### 2. Git 状态
```
git log --oneline -5  # 最新提交状态
```

### 3. 工程状态
```
cat PROJECT_STATUS.md                      # 版本号 + 已知问题 + 修复记录
```

### 4. 部署健康检查
```
docker ps --filter name=mt6-app 2>/dev/null || echo "无 Docker，跳过"
curl -s localhost:19377/health            # API 健康检查
```

违反后果：跳过步骤视为失职，可能基于过期信息决策。

## 会话结束

每次会话结束时**务必**将所做改动记录到 Memory 知识图谱：

1. 创建 `Session` 类型实体，命名格式 `session-YYYY-MM-DD-简要描述`
2. 记录内容：改了什么、为什么改、涉及哪些文件、commit hash、测试结果
3. 同步更新 `LLM Fallback Chain` 实体（如有改动）

## 提交前检查

- 运行相关测试确认通过
- 不提交未完成的代码

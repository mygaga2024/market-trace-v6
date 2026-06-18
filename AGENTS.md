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

每次会话结束时**务必**自动执行收尾工作，无需用户催促：

1. 创建 `Session` 类型实体，命名格式 `session-YYYY-MM-DD-简要描述`
2. 记录内容：改了什么、为什么改、涉及哪些文件、commit hash、测试结果
3. 同步更新 `LLM Fallback Chain` 实体（如有改动）
4. 执行 `git commit` 提交所有更改
5. 更新 `PROJECT_STATUS.md` 的修复记录表
6. 清理临时文件：`__pycache__`、`.pytest_cache`、`*.pyc`、`logs/`、`.DS_Store` 等
7. 三地同步：`git push origin main`（敏感文件已在 .gitignore 排除）

## 任务交付前

每次代码修改完成后、收尾工作前，**务必**执行部署验证。
**部署验证 + 收尾是一个不可分割的整体，验证通过后立刻收尾，不得等到用户提醒。**

### 交付流程（顺序执行，不可跳过）

1. `pytest tests/ -v` → 必须全通过
2. NAS 部署 + health 验证 → 必须返回 ok
3. `git add` + `git commit` + `git push`
4. 更新 `PROJECT_STATUS.md`
5. Memory 记录 Session
6. 清理临时文件

### 执行细节

### 1. 单元测试
```
pytest tests/ -v
```

### 2. Docker 部署验证（NAS 绿联 Docker）
项目部署在绿联 NAS（`ssh nas`）的 Docker 上，每次改动后需实际部署验证：

```
# 上传代码到 NAS（rsync 不可用，用 tar+ssh 管道）
tar czf - --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='logs' --exclude='data' --exclude='venv' --exclude='.venv' \
  --exclude='.env' --exclude='.DS_Store' . \
  | ssh nas "cd /volume1/docker/market-trace-v6 && tar xzf -"

# 修复文件权限（macOS tar 可能留下 600 权限）
ssh nas "chmod -R a+r /volume1/docker/market-trace-v6/"

# 重新构建并启动
ssh nas "cd /volume1/docker/market-trace-v6 && docker compose up -d --build app"

# 等待启动 + 验证
sleep 5
ssh nas "curl -s localhost:19377/health | python3 -m json.tool"
```

### 3. 本地开发时降级验证（无 NAS 访问时）
```
python3 -c "from core.llm_factory import LLMFallbackChain; print('导入成功')"
```

## 提交前检查

- 运行相关测试确认通过
- 部署验证通过
- 不提交未完成的代码

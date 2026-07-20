# AGENTS.md — AI 会话规则

## ⛔ 最高优先级：任务完成判定

以下条件全部满足才算"任务完成"。**任一未满足 = 任务未完成，必须继续。**

```
□ 代码改动已做
□ pytest tests/ -v 全部通过
□ NAS 部署验证 返回 ok
□ NAS 后端 API 实测 已执行 (涉及后端时: curl 调用关键端点验证返回值)
□ 前端 Web 实测 已执行 (涉及前端时: 用 webfetch 抓页面 + curl 调 mock API 验证渲染数据)
□ git add + git commit + git push 已执行
□ PROJECT_STATUS.md 已更新
□ Memory Session 已记录
□ 进化数据已写入 (.project_evolution.yaml)
□ 临时文件已清理
□ git status 显示 clean
```

**收尾不是额外步骤，是任务的一部分。代码改完 ≠ 任务完成。以上全部打勾才算结束。**

**双实测原则：本项目为前后端分离架构，Web 改动 = 后端 + 前端 双验证。**

| 改动范围 | 验证方式 |
|----------|---------|
| 仅后端 (Python/API/Agent) | NAS 部署后 curl 调端点验证返回值 |
| 仅前端 (HTML/CSS/JS) | dev_server + curl 调 mock API 验证数据 + webfetch 抓页面验证结构 |
| 前后端都改 | **两者都做** |

---

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

### 5. 项目进化数据
```
python3 -c "from core.self_evolution import get_evolution_context; print(get_evolution_context())"
```
读取跨会话积累的修复模式、反模式、代码风格偏好。遇到类似错误时优先尝试已记录的修复方案，严格遵守反模式禁止规则。

违反后果：跳过步骤视为失职，可能基于过期信息决策。

## 会话结束

每次会话结束时**务必**自动执行收尾工作，无需用户催促：

1. 创建 `Session` 类型实体，命名格式 `session-YYYY-MM-DD-简要描述`
2. 记录内容：改了什么、为什么改、涉及哪些文件、commit hash、测试结果
3. **写入项目进化数据**：将本会话新发现的修复模式、反模式、风格偏好写入 `.project_evolution.yaml`
   ```
   python3 -c "
   from core.self_evolution import add_fix, add_anti_pattern, add_style_pattern, add_architecture
   # 示例: add_fix('error sig', 'fix desc', ['file.py'], 'session-xxx')
   "
   ```
4. 同步更新 `LLM Fallback Chain` 实体（如有改动）
5. 执行 `git commit` 提交所有更改
6. 更新 `PROJECT_STATUS.md` 的修复记录表
7. 清理临时文件：`__pycache__`、`.pytest_cache`、`*.pyc`、`logs/`、`.DS_Store` 等
8. 三地同步：`git push origin main`（敏感文件已在 .gitignore 排除）

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

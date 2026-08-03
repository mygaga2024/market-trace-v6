"""
Market Trace V6.0 — pytest 全局配置

main.py 会 load_dotenv 加载仓库 env 文件（含 API_TOKEN 占位符），
若注入测试进程会导致 api.deps.verify_token 生效、所有受保护端点 401。
这里在测试收集前将 API_TOKEN 预置为空串：load_dotenv(override=False)
不会覆盖已存在的环境变量，从而保持测试环境的"无认证"语义。
需要测试认证逻辑的文件（tests/test_auth.py）自行 monkeypatch api.deps/api.kline。
"""

from __future__ import annotations

import os

os.environ.setdefault("API_TOKEN", "")

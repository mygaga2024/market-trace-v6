"""
Market Trace V6.0 — API 依赖注入
认证、状态访问等 FastAPI 依赖函数
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Optional

from fastapi import Header, HTTPException, Request
from loguru import logger


# ─────────────────────────────────────────────
# API Token 认证（可选，未配置 API_TOKEN 时跳过）
# ─────────────────────────────────────────────

_API_TOKEN = os.environ.get("API_TOKEN", "")
SESSION_COOKIE_NAME = "mt6_session"

_SESSION_TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", ".session_token")


def _load_session_token() -> str:
    if not _API_TOKEN:
        return ""
    try:
        if os.path.exists(_SESSION_TOKEN_FILE):
            with open(_SESSION_TOKEN_FILE, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    token = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(_SESSION_TOKEN_FILE), exist_ok=True)
        fd = os.open(_SESSION_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
    except Exception:
        pass
    return token


SESSION_TOKEN = _load_session_token()


async def verify_token(request: Request, authorization: str = Header(None)) -> None:
    """Bearer Token 或 httpOnly Cookie 认证，保护消耗资源的端点"""
    if not _API_TOKEN:
        return  # 未配置 token，跳过认证
    # 1) Bearer Token 认证 (外部 API 调用)
    if authorization and authorization.startswith("Bearer ") and authorization[7:] == _API_TOKEN:
        return
    # 2) httpOnly Cookie 认证 (仪表盘浏览器访问，Cookie 存的是 session token 而非原始 API_TOKEN)
    if request:
        cookie_val = request.cookies.get(SESSION_COOKIE_NAME, "")
        if cookie_val and cookie_val == SESSION_TOKEN:
            return
    if authorization and authorization.startswith("Bearer "):
        raise HTTPException(403, "API Token 无效")
    raise HTTPException(401, "缺少认证凭据")


# ─────────────────────────────────────────────
# app.state 访问器
# ─────────────────────────────────────────────

def get_bus(request: Request):
    """获取消息总线实例"""
    return request.app.state.bus


def get_db(request: Request):
    """获取数据库实例"""
    return request.app.state.db


def get_llm_chain(request: Request):
    """获取 LLM 回退链实例"""
    return request.app.state.llm_chain


def get_config(request: Request) -> dict:
    """获取全局配置"""
    return request.app.state.config


def get_strategy_manager(request: Request):
    """获取策略管理器"""
    return request.app.state.strategy_manager


def get_risk_manager(request: Request):
    """获取风控管理器"""
    return request.app.state.risk_manager

"""
Market Trace V6.0 — API 依赖注入
认证、状态访问等 FastAPI 依赖函数
"""

from __future__ import annotations

import hashlib
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

# 生成独立的 session token（不从 API_TOKEN 派生，用 secrets 安全生成）
SESSION_TOKEN = secrets.token_hex(32) if _API_TOKEN else ""


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

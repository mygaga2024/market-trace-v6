"""
Market Trace V6.0 — 日志脱敏过滤器

自动过滤日志中的 IP、密钥、Token 等敏感信息
"""

from __future__ import annotations

import re

_SENSITIVE_PATTERNS = [
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "<IP>"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-<REDACTED>"),
    (re.compile(r"Bearer [a-zA-Z0-9_-]{10,}"), "Bearer <REDACTED>"),
    (re.compile(r"token[=:]\s*[a-zA-Z0-9_-]{10,}", re.IGNORECASE), "token=<REDACTED>"),
    (re.compile(r"api_key[=:]\s*[a-zA-Z0-9_-]{10,}", re.IGNORECASE), "api_key=<REDACTED>"),
    (re.compile(r"password[=:]\s*\S+", re.IGNORECASE), "password=<REDACTED>"),
    (re.compile(r"Authorization[=:]\s*[^\s,]+", re.IGNORECASE), "Authorization=<REDACTED>"),
    (re.compile(r"ssh\s+\S+@\S+", re.IGNORECASE), "ssh <REDACTED>"),
]


def desensitize(record: dict) -> bool:
    """
    Loguru filter: 脱敏日志消息

    用法:
        logger.add(..., filter=desensitize)
    或:
        logger.configure(patcher=log_patcher)
    """
    message = record.get("message", "")
    if not isinstance(message, str):
        return True

    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)

    record["message"] = message
    return True


def log_patcher(record: dict) -> None:
    """Loguru patcher: 修改 record 中的 message"""
    message = record.get("message", "")
    if not isinstance(message, str):
        return

    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)

    record["message"] = message

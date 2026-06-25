"""
Market Trace V6.0 — API 速率限制中间件
基于令牌桶算法的轻量级内存限流，保护 LLM 接口不被滥用
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from loguru import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    令牌桶限流中间件

    - 按 client IP 独立计数
    - 对 /analyze/* 和 /scan/* 等重路径做更严格限制
    - 对 /health 等轻路径放行
    """

    # 重路径（触发 LLM / 数据拉取）
    HEAVY_PREFIXES = ("/analyze/", "/scan/", "/screen/")
    # 白名单路径（不限流）
    WHITELIST_PREFIXES = ("/health", "/static/", "/favicon")

    def __init__(
        self,
        app,
        default_rpm: int = 120,
        heavy_rpm: int = 20,
    ):
        """
        Args:
            default_rpm: 普通接口每分钟请求上限
            heavy_rpm: 重路径（LLM 相关）每分钟请求上限
        """
        super().__init__(app)
        self._default_rpm = default_rpm
        self._heavy_rpm = heavy_rpm
        # {ip: {"tokens": float, "last_refill": float}}
        self._buckets: dict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": float(default_rpm), "last_refill": time.monotonic()}
        )
        self._heavy_buckets: dict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": float(heavy_rpm), "last_refill": time.monotonic()}
        )

    def _refill_and_consume(
        self, bucket: dict[str, float], rpm: int
    ) -> bool:
        """令牌桶：按经过时间补充令牌，尝试消耗1个。返回 True 表示放行。"""
        now = time.monotonic()
        elapsed = now - bucket["last_refill"]
        # 每秒补充 rpm/60 个令牌
        bucket["tokens"] = min(rpm, bucket["tokens"] + elapsed * rpm / 60.0)
        bucket["last_refill"] = now

        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端 IP（考虑反向代理）"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # 白名单放行
        if any(path.startswith(p) for p in self.WHITELIST_PREFIXES):
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        # 重路径使用更严格的限流
        if any(path.startswith(p) for p in self.HEAVY_PREFIXES):
            bucket = self._heavy_buckets[client_ip]
            if not self._refill_and_consume(bucket, self._heavy_rpm):
                logger.warning(
                    "速率限制: {} {} 被拒绝 (IP={}, heavy_rpm={})",
                    request.method, path, client_ip, self._heavy_rpm,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "请求频率过高，请稍后再试",
                        "detail": f"LLM 相关接口限制: {self._heavy_rpm} 次/分钟",
                    },
                )

        # 普通路径限流
        bucket = self._buckets[client_ip]
        if not self._refill_and_consume(bucket, self._default_rpm):
            logger.warning(
                "速率限制: {} {} 被拒绝 (IP={}, default_rpm={})",
                request.method, path, client_ip, self._default_rpm,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "请求频率过高，请稍后再试",
                    "detail": f"普通接口限制: {self._default_rpm} 次/分钟",
                },
            )

        response = await call_next(request)
        return response

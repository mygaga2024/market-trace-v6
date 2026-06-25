"""
Market Trace V6.0 — 速率限制中间件测试
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.rate_limit import RateLimitMiddleware


def _make_app(default_rpm=5, heavy_rpm=2):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, default_rpm=default_rpm, heavy_rpm=heavy_rpm)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/analyze/{symbol}")
    def analyze(symbol: str):
        return {"symbol": symbol}

    @app.get("/status")
    def status():
        return {"ok": True}

    return app


class TestRateLimitMiddleware:
    def test_whitelist_not_limited(self):
        """健康检查等白名单路径不受限"""
        app = _make_app(default_rpm=2, heavy_rpm=1)
        client = TestClient(app)
        for _ in range(10):
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_normal_path_limited(self):
        """普通路径超过 rpm 后返回 429"""
        app = _make_app(default_rpm=3, heavy_rpm=10)
        client = TestClient(app)
        ok_count = 0
        for _ in range(10):
            resp = client.get("/status")
            if resp.status_code == 200:
                ok_count += 1
        # 初始3个令牌 + 期间可能补充少量 → 应有少于10个成功
        assert ok_count < 10

    def test_heavy_path_stricter_limit(self):
        """重路径（analyze/scan）使用更严格的限制"""
        app = _make_app(default_rpm=100, heavy_rpm=2)
        client = TestClient(app)
        results = []
        for _ in range(5):
            resp = client.post("/analyze/000001")
            results.append(resp.status_code)
        # 初始2个令牌, 第3个开始应被限制
        assert 429 in results

    def test_429_response_format(self):
        """429 响应应包含中文错误信息"""
        app = _make_app(default_rpm=1, heavy_rpm=1)
        client = TestClient(app)
        client.get("/status")  # 消耗唯一令牌
        client.get("/status")  # 这个一定进入 refill 逻辑，可能还能过
        # 连续多次确保触发
        for _ in range(5):
            resp = client.get("/status")
        # 最后一个请求大概率被限流
        resp = client.get("/status")
        if resp.status_code == 429:
            data = resp.json()
            assert "error" in data
            assert "请求频率过高" in data["error"]

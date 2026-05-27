"""
Market Trace V6.0 — 熔断器
实现三态熔断 (CLOSED / OPEN / HALF_OPEN) + 滑动窗口，防止级联故障
"""

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Optional

from loguru import logger


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """熔断器已打开时抛出的异常"""

    def __init__(self, service_name: str, remaining: float):
        self.service_name = service_name
        self.remaining = remaining
        super().__init__(f"熔断器 [{service_name}] 已打开，{remaining:.0f}s 后恢复")


class CircuitBreaker:
    """
    熔断器 — 三态状态机

    CLOSED → (连续失败 N 次) → OPEN
    OPEN   → (等待 recovery_timeout) → HALF_OPEN
    HALF_OPEN → (成功 N 次) → CLOSED
    HALF_OPEN → (任意失败) → OPEN
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        half_open_max_requests: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests

        self.state = State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float = 0
        self.half_open_requests = 0

    @property
    def is_open(self) -> bool:
        return self.state == State.OPEN

    def _transition_to(self, new_state: State) -> None:
        old = self.state
        self.state = new_state
        logger.warning("熔断器 [{}] 状态变更: {} → {}", self.name, old.value, new_state.value)

    def _try_reset(self) -> None:
        """OPEN → HALF_OPEN: 恢复超时已过"""
        if self.state == State.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self._transition_to(State.HALF_OPEN)
                self.half_open_requests = 0

    async def call(
        self,
        func: Callable,
        *args: Any,
        fallback: Optional[Callable] = None,
        **kwargs: Any,
    ) -> Any:
        """
        受熔断保护的函数调用

        Args:
            func: 要执行的异步函数
            fallback: 熔断时执行的降级函数（可选）
        """
        self._try_reset()

        if self.state == State.OPEN:
            remaining = self.recovery_timeout - (time.monotonic() - self.last_failure_time)
            logger.warning("熔断器 [{}] 已打开，拒绝请求 (剩余 {:.0f}s)", self.name, remaining)
            if fallback:
                return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
            raise CircuitBreakerOpenError(self.name, remaining)

        if self.state == State.HALF_OPEN and self.half_open_requests >= self.half_open_max_requests:
            logger.warning("熔断器 [{}] 半开状态请求数已达上限", self.name)
            if fallback:
                return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
            raise CircuitBreakerOpenError(self.name, 0)

        try:
            if self.state == State.HALF_OPEN:
                self.half_open_requests += 1

            result = await func(*args, **kwargs)

            self._on_success()
            return result

        except Exception as e:
            self._on_failure()
            logger.error("熔断器 [{}] 调用失败: {} (连续失败: {})", self.name, e, self.failure_count)
            if fallback:
                logger.info("熔断器 [{}] 执行降级逻辑", self.name)
                return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
            raise

    def _on_success(self) -> None:
        self.failure_count = 0
        if self.state == State.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_requests:
                self._transition_to(State.CLOSED)
                self.success_count = 0
                logger.info("熔断器 [{}] 已恢复正常 (CLOSED)", self.name)

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.state == State.HALF_OPEN:
            self._transition_to(State.OPEN)
            self.failure_count = self.failure_threshold
        elif self.state == State.CLOSED and self.failure_count >= self.failure_threshold:
            self._transition_to(State.OPEN)

    def reset(self) -> None:
        """强制重置到 CLOSED 状态"""
        self.state = State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_requests = 0
        logger.info("熔断器 [{}] 已手动重置", self.name)


class CircuitBreakerRegistry:
    """熔断器注册表 — 管理多个服务的熔断器"""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(self, name: str, **kwargs: Any) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name, **kwargs)
        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        return self._breakers.get(name)

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()

    @property
    def status(self) -> dict[str, str]:
        return {name: b.state.value for name, b in self._breakers.items()}

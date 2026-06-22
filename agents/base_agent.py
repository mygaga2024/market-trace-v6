"""
Market Trace V6.0 — Agent 通信基类
所有业务 Agent 继承此基类，获得心跳、消息收发、宕机检测能力
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from core.bus import MessageBus


class BaseAgent(ABC):
    """
    Agent 通信基类

    提供：
    - 心跳机制（定期写入 agent:heartbeat:{name}）
    - Pub/Sub 消息监听与背压控制
    - 跨 Agent 宕机检测与 AGENT_DOWN 事件发布
    - 消息发送 publish()
    - 优雅启停 start() / stop()
    """

    MONITORED_AGENTS = ["macro", "signal", "trace", "risk", "chief"]

    def __init__(
        self,
        name: str,
        bus: MessageBus,
        subscriptions: list[str],
        config: dict[str, Any],
        db=None,
    ):
        self.name = name
        self.bus = bus
        self.subscriptions = subscriptions
        self.config = config
        self.db = db

        agent_cfg = config.get("agents", {})
        self._heartbeat_interval: int = agent_cfg.get("heartbeat_interval", 5)
        self._heartbeat_timeout: int = agent_cfg.get("heartbeat_timeout", 15)
        self._max_concurrent: int = agent_cfg.get("max_concurrent_msgs", 100)
        self._monitor_miss_threshold: int = 3

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._started_at: Optional[datetime] = None
        self._msg_count: int = 0
        self._error_count: int = 0

        self._missed_heartbeats: dict[str, int] = {}

    async def start(self) -> None:
        """启动 Agent 主循环（需在 asyncio 事件循环中调用）"""
        if self._running:
            logger.warning("Agent [{}] 已在运行中", self.name)
            return

        self._running = True
        self._started_at = datetime.now(timezone.utc)
        logger.info("Agent [{}] 启动 | 订阅: {} | 心跳间隔: {}s", self.name, self.subscriptions, self._heartbeat_interval)

        self._tasks = [
            asyncio.create_task(self._heartbeat_loop(), name=f"{self.name}-heartbeat"),
            asyncio.create_task(self._message_loop(), name=f"{self.name}-messages"),
            asyncio.create_task(self._monitor_heartbeats(), name=f"{self.name}-monitor"),
        ]

        self._tasks.append(asyncio.create_task(self.run(), name=f"{self.name}-run"))

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """优雅停止 Agent"""
        logger.info("Agent [{}] 正在停止...", self.name)
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()
        logger.info("Agent [{}] 已停止 | 处理消息: {} | 错误: {}", self.name, self._msg_count, self._error_count)

    # ---- 主循环（子类可重写） ----

    async def run(self) -> None:
        """
        Agent 主业务循环（子类可重写）

        默认定时空闲循环，子类可在其中实现：
        - Macro Agent: 定时拉取宏观数据
        - Signal Agent: 被动响应，无需重写
        - Trace Agent: 被动响应，无需重写
        - Risk Agent: 定时扫描检查
        - Chief Analyst: 定时汇总决策
        """
        while self._running:
            await asyncio.sleep(1)

    # ---- 消息处理 ----

    @abstractmethod
    async def process_message(self, message: dict[str, Any]) -> None:
        """
        处理接收到的消息（子类必须实现）

        Args:
            message: 反序列化后的 JSON 消息字典
        """
        ...

    async def _message_loop(self) -> None:
        """消息监听主循环（含背压控制）"""
        pubsub = await self.bus.subscribe(*self.subscriptions)
        semaphore = asyncio.Semaphore(self._max_concurrent)

        try:
            async for message in self.bus.listen(pubsub):
                if not self._running:
                    break

                await semaphore.acquire()
                asyncio.create_task(self._process_safe(message, semaphore))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Agent [{}] 消息循环异常: {}", self.name, e)
        finally:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception:
                pass

    async def _process_safe(
        self, message: dict[str, Any], semaphore: Optional[asyncio.Semaphore] = None
    ) -> None:
        """安全处理单条消息（异常隔离），处理完毕后释放信号量"""
        try:
            await self.process_message(message)
            self._msg_count += 1
        except Exception as e:
            self._error_count += 1
            logger.error("Agent [{}] 消息处理异常: {} | 消息: {}", self.name, e, str(message)[:200])
        finally:
            if semaphore is not None:
                semaphore.release()

    # ---- 消息发布 ----

    async def publish(self, channel: str, payload: dict[str, Any]) -> int:
        """
        发布消息到指定频道

        Returns:
            Redis 返回的接收订阅者数量
        """
        return await self.bus.publish(channel, payload)

    # ---- 心跳机制 ----

    async def _heartbeat_loop(self) -> None:
        """心跳主循环：定期写入 agent:heartbeat:{name}"""
        while self._running:
            try:
                await self.bus.publish_heartbeat(self.name)
            except Exception as e:
                logger.warning("Agent [{}] 心跳写入失败: {}", self.name, e)
            await asyncio.sleep(self._heartbeat_interval)

    async def _monitor_heartbeats(self) -> None:
        """
        监控其他 Agent 心跳

        连续丢失超过 miss_threshold 次 → 发布 AGENT_DOWN
        恢复时 → 发布 AGENT_UP
        """
        others = [a for a in self.MONITORED_AGENTS if a != self.name]
        count = 0

        while self._running:
            await asyncio.sleep(self._heartbeat_timeout)
            count += 1

            heartbeats = await self.bus.check_all_heartbeats(others)

            for agent_name, alive in heartbeats.items():
                prev_missed = self._missed_heartbeats.get(agent_name, 0)

                if not alive:
                    self._missed_heartbeats[agent_name] = prev_missed + 1
                    new_missed = prev_missed + 1

                    if new_missed == self._monitor_miss_threshold:
                        logger.warning("Agent [{}] 检测到 [{}] 无响应 (连续 {} 次)", self.name, agent_name, new_missed)
                        await self.bus.publish("events:system", {
                            "event": "AGENT_DOWN",
                            "agent": agent_name,
                            "detected_by": self.name,
                            "consecutive_misses": new_missed,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

                elif alive and prev_missed >= self._monitor_miss_threshold:
                    logger.info("Agent [{}] 检测到 [{}] 已恢复", self.name, agent_name)
                    self._missed_heartbeats[agent_name] = 0
                    await self.bus.publish("events:system", {
                        "event": "AGENT_UP",
                        "agent": agent_name,
                        "detected_by": self.name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                elif alive:
                    self._missed_heartbeats[agent_name] = 0

    # ---- 生命周期工具 ----

    async def _cleanup(self) -> None:
        """清理资源"""
        await self.bus.publish("events:system", {
            "event": "AGENT_STOPPED",
            "agent": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Agent [{}] 资源已清理", self.name)

    @property
    def stats(self) -> dict[str, Any]:
        """Agent 运行统计"""
        uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds() if self._started_at else 0
        return {
            "name": self.name,
            "running": self._running,
            "uptime_seconds": round(uptime, 1),
            "messages_processed": self._msg_count,
            "errors": self._error_count,
            "subscriptions": self.subscriptions,
            "concurrent_limit": self._max_concurrent,
        }

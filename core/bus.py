"""
Market Trace V6.0 — Redis 异步消息总线
提供 Pub/Sub 和 Stream 两种消息模式，含自动重连与心跳支持
"""

import asyncio
import json
from typing import Any, AsyncIterator, Optional

import redis.asyncio as aioredis
from loguru import logger


class MessageBus:
    """Redis 异步消息总线封装"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str = "",
        max_connections: int = 10,
        retry_interval: int = 5,
        health_check_interval: int = 30,
    ):
        self._redis_url = f"redis://{host}:{port}/{db}"
        self._password = password or None
        self._max_connections = max_connections
        self._retry_interval = retry_interval
        self._redis: Optional[aioredis.Redis] = None
        self._subscribers: list[aioredis.client.PubSub] = []
        self._connected = False
        self._health_task: Optional[asyncio.Task] = None

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("MessageBus not connected. Call connect() first.")
        return self._redis

    async def connect(self, max_retries: int = 0) -> None:
        """建立连接，失败时自动重试。max_retries=0 表示无限重试"""
        attempt = 0
        while not self._connected:
            attempt += 1
            try:
                self._redis = aioredis.from_url(
                    self._redis_url,
                    password=self._password,
                    max_connections=self._max_connections,
                    decode_responses=True,
                    socket_keepalive=True,
                    health_check_interval=self._retry_interval,
                )
                await self._redis.ping()
                self._connected = True
                logger.info("MessageBus 已连接到 Redis ({})", self._redis_url)
            except Exception as e:
                if max_retries and attempt >= max_retries:
                    logger.error("Redis 连接失败 (已重试{}次): {}", attempt, e)
                    raise
                logger.warning("Redis 连接失败 (第{}次): {}。{}秒后重试...", attempt, e, self._retry_interval)
                await asyncio.sleep(self._retry_interval)

    async def close(self) -> None:
        """优雅关闭连接"""
        for sub in self._subscribers:
            try:
                await sub.unsubscribe()
                await sub.close()
            except Exception:
                pass
        self._subscribers.clear()

        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
        self._connected = False
        logger.info("MessageBus 已断开 Redis 连接")

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._redis:
            return False
        try:
            return await self._redis.ping()
        except Exception:
            return False

    async def publish(self, channel: str, payload: dict[str, Any]) -> int:
        """发布消息到指定频道"""
        message = json.dumps(payload, ensure_ascii=False, default=str)
        count = await self.redis.publish(channel, message)
        logger.debug("发布 → {} : {}", channel, payload.get("event", "unknown"))
        return count

    async def xadd(self, stream: str, payload: dict[str, Any], maxlen: int = 10000) -> str:
        """写入 Stream（适合需要持久化重放的消息）"""
        message_id = await self.redis.xadd(stream, payload, maxlen=maxlen, approximate=True)
        logger.debug("Stream 写入 → {} : {}", stream, message_id)
        return message_id

    async def xread(
        self, stream: str, last_id: str = "$", block: int = 5000
    ) -> list[tuple[str, list[tuple[str, dict]]]]:
        """阻塞读取 Stream"""
        return await self.redis.xread({stream: last_id}, block=block)

    async def subscribe(self, *channels: str) -> aioredis.client.PubSub:
        """订阅频道，返回 PubSub 对象用于异步迭代"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(*channels)
        self._subscribers.append(pubsub)
        logger.info("已订阅频道: {}", channels)
        return pubsub

    async def listen(self, pubsub: aioredis.client.PubSub) -> AsyncIterator[dict[str, Any]]:
        """异步迭代 PubSub 消息"""
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    yield data
                except json.JSONDecodeError:
                    logger.warning("消息解析失败: {}", message["data"][:200])
                except Exception as e:
                    logger.error("消息处理异常: {}", e)

    async def publish_heartbeat(self, agent_name: str) -> None:
        """Agent 心跳"""
        await self.redis.setex(f"agent:heartbeat:{agent_name}", 15, "alive")

    async def get_heartbeat(self, agent_name: str) -> Optional[str]:
        """读取 Agent 心跳"""
        return await self.redis.get(f"agent:heartbeat:{agent_name}")

    async def check_all_heartbeats(self, agent_names: list[str]) -> dict[str, bool]:
        """批量检查 Agent 存活状态"""
        pipe = self.redis.pipeline()
        for name in agent_names:
            pipe.get(f"agent:heartbeat:{name}")
        results = await pipe.execute()
        return {name: (results[i] is not None) for i, name in enumerate(agent_names)}

    async def cache_set(self, key: str, value: Any, ttl: int = 300) -> None:
        """缓存写入"""
        await self.redis.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))

    async def cache_get(self, key: str) -> Optional[Any]:
        """缓存读取"""
        val = await self.redis.get(key)
        if val:
            return json.loads(val)
        return None

"""
Market Trace V6.0 — Agent 通信骨架单元测试
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.bus import MessageBus
from agents.base_agent import BaseAgent


# ---- 测试辅助 ----

class TestAgent(BaseAgent):
    """用于测试的具体 Agent 实现"""

    def __init__(self, name, bus, config, subscriptions=None):
        super().__init__(name, bus, subscriptions or ["test:channel"], config)
        self.received_messages: list[dict] = []
        self.processed_event = asyncio.Event()

    async def process_message(self, message: dict) -> None:
        self.received_messages.append(message)
        self.processed_event.set()

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(0.1)


class ErrorAgent(BaseAgent):
    """模拟消息处理异常的 Agent"""

    def __init__(self, name, bus, config):
        super().__init__(name, bus, ["test:channel"], config)

    async def process_message(self, message: dict) -> None:
        raise ValueError("模拟异常")

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(0.1)


@pytest.fixture
def config() -> dict:
    return {
        "agents": {
            "heartbeat_interval": 1,
            "heartbeat_timeout": 2,
            "max_concurrent_msgs": 5,
        }
    }


@pytest.fixture
def mock_bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish = AsyncMock(return_value=1)
    bus.publish_heartbeat = AsyncMock()
    bus.check_all_heartbeats = AsyncMock(return_value={
        "macro": True, "signal": True, "trace": True, "risk": True, "chief": True,
    })
    bus.cache_set = AsyncMock()
    bus.cache_get = AsyncMock(return_value=None)
    return bus


# ---- Heartbeat Tests ----

@pytest.mark.asyncio
async def test_heartbeat_published_periodically(config, mock_bus):
    cfg = {"agents": {"heartbeat_interval": 1, "heartbeat_timeout": 15, "max_concurrent_msgs": 5}}
    agent = TestAgent("test-agent", mock_bus, cfg)
    agent._running = True

    task = asyncio.create_task(agent._heartbeat_loop())
    await asyncio.sleep(1.2)
    agent._running = False
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert mock_bus.publish_heartbeat.call_count >= 1
    mock_bus.publish_heartbeat.assert_called_with("test-agent")


@pytest.mark.asyncio
async def test_heartbeat_continues_after_error(config, mock_bus):
    call_count = 0

    async def flaky_heartbeat(name):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("模拟连接失败")

    mock_bus.publish_heartbeat = flaky_heartbeat

    cfg = {"agents": {"heartbeat_interval": 1, "heartbeat_timeout": 15, "max_concurrent_msgs": 5}}
    agent = TestAgent("test-agent", mock_bus, cfg)
    agent._running = True

    task = asyncio.create_task(agent._heartbeat_loop())
    await asyncio.sleep(1.2)
    agent._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert call_count >= 2


# ---- Message Processing Tests ----

@pytest.mark.asyncio
async def test_process_message_called(config, mock_bus):
    agent = TestAgent("test-agent", mock_bus, config)
    msg = {"event": "TEST", "data": "hello"}

    await agent.process_message(msg)

    assert len(agent.received_messages) == 1
    assert agent.received_messages[0] == msg


@pytest.mark.asyncio
async def test_error_agent_does_not_crash(config, mock_bus):
    agent = ErrorAgent("error-agent", mock_bus, config)
    msg = {"event": "TEST"}

    await agent._process_safe(msg)

    assert agent._error_count == 1
    assert agent._msg_count == 0


@pytest.mark.asyncio
async def test_message_loop_backpressure_semaphore(config, mock_bus):
    """验证 Semaphore 背压控制：并发数不超过 max_concurrent"""
    active_tasks = 0
    max_observed = 0

    class CountingAgent(BaseAgent):
        def __init__(self):
            super().__init__("counter", mock_bus, ["test"], config)

        async def process_message(self, msg):
            nonlocal active_tasks, max_observed
            active_tasks += 1
            max_observed = max(max_observed, active_tasks)
            await asyncio.sleep(0.02)
            active_tasks -= 1

        async def run(self):
            while self._running:
                await asyncio.sleep(0.1)

    agent = CountingAgent()

    messages = []
    for i in range(30):
        messages.append(AsyncMock())
        messages[-1].__getitem__ = lambda self, k, msg={"event": f"msg_{i}"}: msg if k == "data" else "message"

    async def fake_listen(pubsub):
        for i in range(30):
            yield {"event": f"msg_{i}"}
            await asyncio.sleep(0.001)

    with patch.object(agent.bus, "subscribe", new_callable=AsyncMock) as mock_sub:
        with patch.object(agent.bus, "listen", wraps=fake_listen) as mock_listen:
            mock_pubsub = MagicMock()
            mock_pubsub.unsubscribe = AsyncMock()
            mock_pubsub.close = AsyncMock()
            mock_sub.return_value = mock_pubsub

            agent._running = True
            task = asyncio.create_task(agent._message_loop())
            await asyncio.sleep(0.5)
            agent._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert max_observed <= config["agents"]["max_concurrent_msgs"]


# ---- Publish Tests ----

@pytest.mark.asyncio
async def test_publish_delegates_to_bus(config, mock_bus):
    agent = TestAgent("test-agent", mock_bus, config)
    payload = {"event": "CUSTOM", "value": 42}

    result = await agent.publish("reports:test", payload)

    mock_bus.publish.assert_called_once_with("reports:test", payload)
    assert result == 1


# ---- AGENT_DOWN / AGENT_UP Tests ----

@pytest.mark.asyncio
async def test_agent_down_detection(config, mock_bus):
    """连续 3 次心跳丢失应触发 AGENT_DOWN"""
    call_count = 0

    async def dead_heartbeats(names):
        nonlocal call_count
        call_count += 1
        result = {}
        for n in names:
            result[n] = call_count <= 3
        return result

    mock_bus.check_all_heartbeats = dead_heartbeats

    agent = TestAgent("test-agent", mock_bus, config)
    agent._running = True
    agent._monitor_miss_threshold = 3
    agent._heartbeat_timeout = 0.01

    task = asyncio.create_task(agent._monitor_heartbeats())
    await asyncio.sleep(0.5)
    agent._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    down_events = [
        c for c in mock_bus.publish.call_args_list
        if "events:system" in c[0] and c[0][1].get("event") == "AGENT_DOWN"
    ]
    assert len(down_events) >= 1


@pytest.mark.asyncio
async def test_agent_up_detection(config, mock_bus):
    """心跳恢复应触发 AGENT_UP"""
    call_count = 0

    async def variable_heartbeats(names):
        nonlocal call_count
        call_count += 1
        result = {}
        for n in names:
            result[n] = call_count > 5
        return result

    mock_bus.check_all_heartbeats = variable_heartbeats

    agent = TestAgent("test-agent", mock_bus, config)
    agent._running = True
    agent._monitor_miss_threshold = 3
    agent._heartbeat_timeout = 0.01

    task = asyncio.create_task(agent._monitor_heartbeats())
    await asyncio.sleep(0.8)
    agent._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    up_events = [
        c for c in mock_bus.publish.call_args_list
        if "events:system" in c[0] and c[0][1].get("event") == "AGENT_UP"
    ]
    assert len(up_events) >= 1


@pytest.mark.asyncio
async def test_agent_does_not_monitor_self(config, mock_bus):
    """Agent 不应监控自己的心跳"""
    self_checked = False

    async def track_call(names):
        nonlocal self_checked
        if "test-agent" in names:
            self_checked = True
        return {n: True for n in names}

    mock_bus.check_all_heartbeats = track_call

    agent = TestAgent("test-agent", mock_bus, config)
    agent._running = True
    agent._heartbeat_timeout = 0.01

    task = asyncio.create_task(agent._monitor_heartbeats())
    await asyncio.sleep(0.05)
    agent._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert not self_checked


# ---- Stats & Lifecycle Tests ----

@pytest.mark.asyncio
async def test_stats_tracking(config, mock_bus):
    agent = TestAgent("test-agent", mock_bus, config)
    agent._started_at = datetime.now(timezone.utc)
    agent._msg_count = 10
    agent._error_count = 2

    stats = agent.stats

    assert stats["name"] == "test-agent"
    assert stats["messages_processed"] == 10
    assert stats["errors"] == 2
    assert stats["concurrent_limit"] == 5


@pytest.mark.asyncio
async def test_cleanup_publishes_stopped_event(config, mock_bus):
    agent = TestAgent("test-agent", mock_bus, config)

    await agent._cleanup()

    stopped = [
        c for c in mock_bus.publish.call_args_list
        if "events:system" in c[0] and c[0][1].get("event") == "AGENT_STOPPED"
    ]
    assert len(stopped) == 1
    assert stopped[0][0][1]["agent"] == "test-agent"


@pytest.mark.asyncio
async def test_stop_cancels_tasks(config, mock_bus):
    agent = TestAgent("test-agent", mock_bus, config)
    agent._running = True
    agent._tasks = [asyncio.create_task(asyncio.sleep(10))]

    await agent.stop()

    assert agent._running is False
    for t in agent._tasks:
        assert t.done() or t.cancelled()


# ---- Concrete Subclass Requirement ----

def test_cannot_instantiate_abstract(mock_bus, config):
    """直接实例化 BaseAgent 应抛出 TypeError"""
    with pytest.raises(TypeError):
        BaseAgent("x", mock_bus, ["ch"], config)


def test_concrete_subclass_instantiates(mock_bus, config):
    agent = TestAgent("concrete", mock_bus, config)
    assert agent.name == "concrete"
    assert agent.subscriptions == ["test:channel"]

"""
Market Trace V6.0 — 历史行情重放引擎
按时间戳顺序发射 DATA_UPDATED 事件，支持实时/批量两种模式
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from core.bus import MessageBus


@dataclass
class ReplayConfig:
    """重放配置"""
    symbol: str
    speed: float = 0.0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_events: int = 0


@dataclass
class ReplayProgress:
    """重放进度"""
    total: int = 0
    processed: int = 0
    errors: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def pct(self) -> float:
        return self.processed / max(self.total, 1) * 100

    @property
    def done(self) -> bool:
        return self.processed >= self.total


class MarketReplay:
    """
    历史行情重放引擎

    支持两种模式：
    - speed=0: 批量重放（立即发射所有事件，适合快速回测）
    - speed>0: 实时重放（按真实时间间隔 × speed 倍数播放）
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._progress: dict[str, ReplayProgress] = {}
        self._running = False

    async def replay(self, config: ReplayConfig, data: list[dict[str, Any]]) -> ReplayProgress:
        """
        重放历史数据

        Args:
            config: 重放配置（symbol, speed, date range）
            data: 标准化 K 线数据列表（需包含 timestamp 字段）

        Returns:
            ReplayProgress 进度对象
        """
        if not data:
            logger.warning("重放数据为空: {}", config.symbol)
            return ReplayProgress()

        self._running = True

        sorted_data = sorted(data, key=lambda x: _parse_ts(x.get("timestamp", "")) or datetime.min)
        if config.start_date:
            sd = _parse_ts(config.start_date)
            if sd:
                sorted_data = [d for d in sorted_data if (_parse_ts(d.get("timestamp", "")) or datetime.min) >= sd]
        if config.end_date:
            ed = _parse_ts(config.end_date)
            if ed:
                sorted_data = [d for d in sorted_data if (_parse_ts(d.get("timestamp", "")) or datetime.max) <= ed]
        if config.max_events > 0:
            sorted_data = sorted_data[-config.max_events:]

        progress = ReplayProgress(
            total=len(sorted_data),
            started_at=datetime.now(timezone.utc),
        )
        self._progress[config.symbol] = progress

        logger.info("开始重放 {}: {} 条数据, speed={}", config.symbol, progress.total, config.speed)

        if config.speed == 0:
            await self._replay_batch(config.symbol, sorted_data, progress)
        else:
            await self._replay_realtime(config.symbol, sorted_data, config.speed, progress)

        progress.finished_at = datetime.now(timezone.utc)
        self._running = False
        logger.info("重放完成 {}: {}/{} 成功, {} 错误", config.symbol, progress.processed, progress.total, progress.errors)
        return progress

    async def _replay_batch(
        self, symbol: str, data: list[dict], progress: ReplayProgress
    ) -> None:
        """批量重放：一次性发射所有事件"""
        for item in data:
            if not self._running:
                break
            try:
                await self._emit(symbol, item)
                progress.processed += 1
            except Exception as e:
                progress.errors += 1
                logger.error("重放异常 {}: {}", symbol, e)

    async def _replay_realtime(
        self, symbol: str, data: list[dict], speed: float, progress: ReplayProgress
    ) -> None:
        """实时重放：按时间间隔发射"""
        last_ts: Optional[datetime] = None
        for item in data:
            if not self._running:
                break

            current_ts = _parse_ts(item.get("timestamp", ""))
            if last_ts and current_ts:
                delay = (current_ts - last_ts).total_seconds() / speed
                if delay > 0:
                    await asyncio.sleep(min(delay, 5.0))

            try:
                await self._emit(symbol, item)
                progress.processed += 1
                last_ts = current_ts
            except Exception as e:
                progress.errors += 1
                logger.error("重放异常 {}: {}", symbol, e)

    async def _emit(self, symbol: str, item: dict[str, Any]) -> None:
        """发射单条数据事件"""
        await self.bus.publish("events:data", {
            "event": "DATA_UPDATED",
            "symbol": symbol,
            "source": "replay",
            "data": item,
            "timestamp": item.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "replay": True,
        })

    def stop(self) -> None:
        """停止重放"""
        self._running = False
        logger.info("重放已停止")

    def get_progress(self, symbol: str) -> Optional[ReplayProgress]:
        return self._progress.get(symbol)


def _parse_ts(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            try:
                return datetime.strptime(ts, "%Y-%m-%d")
            except (ValueError, TypeError):
                pass
    return None

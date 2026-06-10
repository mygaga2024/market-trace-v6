"""
Market Trace V6.0 — 策略生命周期管理器

追踪策略运行状态、连续失败计数、自动下线。
状态存储在 Redis 中，重启不丢失。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger


def _cache_prefix(name: str) -> str:
    return f"strategy:{name}"


class StrategyManager:
    """管理策略的生命周期：启用/禁用、连续失败计数、自动下线"""

    def __init__(
        self,
        bus,
        consecutive_loss_threshold: int = 10,
        min_win_rate: float = 0.35,
        min_score: float = -1.0,
        min_total_trades: int = 3,
    ):
        self.bus = bus
        self.consecutive_loss_threshold = consecutive_loss_threshold
        self.min_win_rate = min_win_rate
        self.min_score = min_score
        self.min_total_trades = min_total_trades

    async def get_active_strategies(self) -> list[str]:
        from backtest.strategy_backtest import STRATEGIES
        active = []
        for name in STRATEGIES:
            state = await self._get_state(name) if self.bus else {}
            if state.get("status", "active") == "active":
                active.append(name)
        return active

    async def get_all_strategies(self) -> dict[str, dict[str, Any]]:
        from backtest.strategy_backtest import STRATEGIES
        result = {}
        for name, label in STRATEGIES.items():
            state = await self._get_state(name) if self.bus else {}
            result[name] = {
                "label": label,
                "status": state.get("status", "active"),
                "consecutive_losses": int(state.get("consecutive_losses", 0)),
                "disabled_reason": state.get("disabled_reason", ""),
                "last_score": float(state.get("last_score", 0)),
                "last_run": state.get("last_run", ""),
            }
        return result

    async def disable_strategy(self, name: str, reason: str) -> None:
        if self.bus:
            prefix = _cache_prefix(name)
            await self.bus.cache_set(
                prefix, {"status": "disabled", "disabled_reason": reason},
                ttl=86400 * 30,
            )
        logger.warning("策略 [{}] 已自动禁用: {}", name, reason)

    async def enable_strategy(self, name: str) -> None:
        if self.bus:
            prefix = _cache_prefix(name)
            await self.bus.cache_set(
                prefix, {"status": "active", "consecutive_losses": 0, "disabled_reason": ""},
                ttl=86400 * 30,
            )
        logger.info("策略 [{}] 已重新启用", name)

    async def evaluate_health(self, results: dict[str, dict[str, Any]]) -> dict[str, str]:
        """回测完成后评估每个策略的健康状况，仅记录警告不自动禁用"""
        from backtest.strategy_backtest import STRATEGIES

        changes: dict[str, str] = {}

        for name in STRATEGIES:
            if not self.bus:
                continue

            state = await self._get_state(name)

            agg = self._aggregate(results, name)

            is_healthy = (
                agg["total_trades"] >= self.min_total_trades
                and agg["avg_win_rate"] >= self.min_win_rate
                and agg["avg_score"] >= self.min_score
            )

            consecutive = int(state.get("consecutive_losses", 0))

            if is_healthy:
                if consecutive > 0:
                    await self._set_state(name, "consecutive_losses", 0)
                    logger.info("策略 [{}] 恢复健康，重置连续失败计数", name)
                    changes[name] = "reset"
            else:
                consecutive += 1
                await self._set_state(name, "consecutive_losses", consecutive)
                await self._set_state(name, "last_score", round(agg["avg_score"], 2))

                if consecutive >= self.consecutive_loss_threshold:
                    logger.warning(
                        "策略 [{}] 连续 {} 次不合格 (胜率 {:.0%}, 评分 {:.2f}, 交易 {} 笔) — 未自动禁用",
                        name, consecutive, agg["avg_win_rate"], agg["avg_score"], agg["total_trades"]
                    )
                    changes[name] = "warning"
                else:
                    changes[name] = f"consecutive_loss_{consecutive}"

            now = datetime.now(timezone.utc).isoformat()
            await self._set_state(name, "last_run", now)

        return changes

    def _aggregate(self, results: dict[str, dict[str, Any]], strategy: str) -> dict[str, Any]:
        scores = []
        win_rates = []
        total_trades = 0

        for symbol, strats in results.items():
            if strategy in strats:
                s = strats[strategy]
                scores.append(s["score"])
                win_rates.append(s["win_rate_pct"] / 100)
                total_trades += s["total_trades"]

        if not scores:
            return {"avg_score": -999, "avg_win_rate": 0, "total_trades": 0}

        return {
            "avg_score": sum(scores) / len(scores),
            "avg_win_rate": sum(win_rates) / len(win_rates),
            "total_trades": total_trades,
        }

    async def _get_state(self, name: str) -> dict[str, Any]:
        if not self.bus:
            return {"status": "active", "consecutive_losses": 0}
        cached = await self.bus.cache_get(_cache_prefix(name))
        if cached:
            return cached
        return {"status": "active", "consecutive_losses": 0}

    async def _set_state(self, name: str, key: str, value: Any) -> None:
        if not self.bus:
            return
        existing = await self.bus.cache_get(_cache_prefix(name))
        state = existing if existing else {"status": "active", "consecutive_losses": 0}
        state[key] = value
        await self.bus.cache_set(_cache_prefix(name), state, ttl=86400 * 30)

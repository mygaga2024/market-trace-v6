"""
Market Trace V6.0 — 风控闭环管理器

追踪风险事件历史，维护风险等级状态，集成仓位建议，
实现"检测→记录→反馈→自适应"的闭环。

状态存储在 Redis，重启不丢失。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from loguru import logger

RISK_STATE_KEY = "risk:state"
RISK_OVERRIDES_KEY = "risk:overrides"


class RiskManager:
    """风控闭环：事件追踪、等级评估、仓位建议、自适应阈值"""

    def __init__(
        self,
        bus,
        config: dict[str, Any],
    ):
        self.bus = bus
        rm_cfg = config.get("risk_manager", {})
        self._elevated_threshold: int = rm_cfg.get("elevated_threshold", 3)
        self._critical_threshold: int = rm_cfg.get("critical_threshold", 5)
        self._cooldown_minutes: int = rm_cfg.get("cooldown_minutes", 60)
        self._max_override_history: int = rm_cfg.get("max_override_history", 100)
        self._adaptive_params_enabled: bool = rm_cfg.get("adaptive_params_enabled", True)

    async def record_override(self, reason: str, action: str, severity: str, symbol: str = "") -> None:
        """记录一次风控否决事件并更新风险状态"""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "action": action,
            "severity": severity,
            "symbol": symbol,
        }
        await self._append_override(event)
        await self._update_risk_state(event)

    async def get_risk_state(self) -> dict[str, Any]:
        """当前风险状态"""
        state = await self._load_state() if self.bus else {}
        return {
            "level": state.get("level", "normal"),
            "daily_overrides": int(state.get("daily_overrides", 0)),
            "total_overrides": int(state.get("total_overrides", 0)),
            "last_override_time": state.get("last_override_time", ""),
            "last_critical_time": state.get("last_critical_time", ""),
            "current_circuit_breaker": state.get("circuit_breaker", "none"),
            "adaptive_suggestion": state.get("adaptive_suggestion", ""),
        }

    async def get_override_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """最近的风控否决事件列表"""
        if not self.bus:
            return []
        events = await self.bus.cache_get(RISK_OVERRIDES_KEY)
        if not events:
            return []
        return events[-limit:][::-1]

    async def get_position_suggestion(
        self,
        symbol: str,
        capital: float = 100000,
        price: float = 10.0,
        method: str = "kelly",
        **kwargs,
    ) -> dict[str, Any]:
        """根据当前风险状态给出仓位建议"""
        from core.position_sizing import kelly_criterion, equal_weight, risk_parity

        state = await self.get_risk_state()
        risk_multiplier = self._risk_multiplier(state["level"])

        if method == "kelly":
            win_prob = kwargs.get("win_prob", 0.5)
            avg_win = kwargs.get("avg_win", 0.03)
            avg_loss = kwargs.get("avg_loss", 0.02)
            kelly_fraction = kwargs.get("kelly_fraction", 0.5)
            pct = kelly_criterion(win_prob, avg_win, avg_loss, kelly_fraction)
            detail = f"凯利公式(F={kelly_fraction}) × 风险乘数({risk_multiplier:.0%})"
        elif method == "equal":
            num_stocks = kwargs.get("num_stocks", 5)
            pct = equal_weight(num_stocks)
            detail = f"等权重({num_stocks}只) × 风险乘数({risk_multiplier:.0%})"
        elif method == "parity":
            volatilities = kwargs.get("volatilities", [0.2, 0.3, 0.25, 0.35, 0.28])
            weights = risk_parity(volatilities)
            pct = weights[0] if weights and len(weights) > 0 else 0.1
            detail = f"风险平价 × 风险乘数({risk_multiplier:.0%})"
        else:
            pct = 0.1
            detail = f"默认 10% × 风险乘数({risk_multiplier:.0%})"

        adjusted_pct = min(pct * risk_multiplier, 0.25)
        amount = capital * adjusted_pct
        lot = 100
        shares = int(amount / price / lot) * lot if price > 0 else 0

        return {
            "method": method,
            "risk_level": state["level"],
            "risk_multiplier": risk_multiplier,
            "position_pct": round(adjusted_pct, 4),
            "shares": shares,
            "amount": round(price * shares, 2),
            "detail": detail,
            "warning": (
                "当前风险等级较高，建议减仓或观望" if state["level"] in ("elevated", "critical")
                else ""
            ),
        }

    async def clear_daily_counters(self) -> None:
        """每日重置计数器（由定时任务调用）"""
        if not self.bus:
            return
        state = await self._load_state()
        state["daily_overrides"] = 0
        await self._save_state(state)
        logger.info("风险管理器: 每日计数器已重置")

    def _risk_multiplier(self, level: str) -> float:
        """风险等级对应的仓位乘数"""
        return {"normal": 1.0, "elevated": 0.5, "critical": 0.25}.get(level, 1.0)

    async def _append_override(self, event: dict) -> None:
        if not self.bus:
            return
        events = await self.bus.cache_get(RISK_OVERRIDES_KEY) or []
        events.append(event)
        if len(events) > self._max_override_history:
            events = events[-self._max_override_history:]
        await self.bus.cache_set(RISK_OVERRIDES_KEY, events, ttl=86400 * 30)

    async def _update_risk_state(self, event: dict) -> None:
        if not self.bus:
            return
        state = await self._load_state()

        now = datetime.now(timezone.utc)
        last_time_str = state.get("last_override_time", "")
        if last_time_str:
            try:
                last_time = datetime.fromisoformat(last_time_str)
                if (now - last_time) > timedelta(hours=24):
                    state["daily_overrides"] = 0
            except (ValueError, TypeError):
                pass

        state["daily_overrides"] = int(state.get("daily_overrides", 0)) + 1
        state["total_overrides"] = int(state.get("total_overrides", 0)) + 1
        state["last_override_time"] = now.isoformat()

        if event.get("severity") == "critical":
            state["last_critical_time"] = now.isoformat()
            state["level"] = "critical"
            state["circuit_breaker"] = "daily_drop"
            state["adaptive_suggestion"] = "建议检查止损阈值，考虑扩大 ATR 倍数"
        elif state["daily_overrides"] >= self._critical_threshold:
            state["level"] = "critical"
            state["circuit_breaker"] = "override_count"
            state["adaptive_suggestion"] = "风控事件密集，建议暂停交易"
        elif state["daily_overrides"] >= self._elevated_threshold:
            state["level"] = "elevated"
            state["circuit_breaker"] = "none"
            state["adaptive_suggestion"] = ""
        else:
            last_critical_str = state.get("last_critical_time", "")
            if last_critical_str:
                try:
                    last_critical = datetime.fromisoformat(last_critical_str)
                    if (now - last_critical) > timedelta(minutes=self._cooldown_minutes):
                        state["level"] = "elevated"
                        state["circuit_breaker"] = "none"
                except (ValueError, TypeError):
                    pass
            else:
                state["level"] = "normal"
                state["circuit_breaker"] = "none"

        await self._save_state(state)

    async def _load_state(self) -> dict[str, Any]:
        if not self.bus:
            return {"level": "normal", "daily_overrides": 0, "total_overrides": 0}
        state = await self.bus.cache_get(RISK_STATE_KEY)
        if state:
            return state
        return {"level": "normal", "daily_overrides": 0, "total_overrides": 0}

    async def _save_state(self, state: dict) -> None:
        if not self.bus:
            return
        await self.bus.cache_set(RISK_STATE_KEY, state, ttl=86400 * 60)

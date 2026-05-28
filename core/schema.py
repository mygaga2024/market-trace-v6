"""
Market Trace V6.0 — 数据交换协议
所有 Agent 间通信和持久化均使用这些 dataclass，严禁随意修改字段
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class AgentName(str, Enum):
    MACRO = "macro"
    SIGNAL = "signal"
    TRACE = "trace"
    RISK = "risk"
    CHIEF = "chief"


class EventType(str, Enum):
    DATA_UPDATED = "DATA_UPDATED"
    AGENT_DOWN = "AGENT_DOWN"
    HEARTBEAT = "HEARTBEAT"
    RISK_OVERRIDE = "RISK_OVERRIDE"
    DECISION_FINAL = "DECISION_FINAL"


class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    WAIT = "WAIT"


class ReportStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    STALE = "stale"
    ERROR = "error"


class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FALLBACK = "fallback"


@dataclass
class MarketData:
    """标准化市场数据"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None
    source: str = "unknown"

    def __post_init__(self):
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)


@dataclass
class Level2Snapshot:
    """Level-2 快照（逐笔委托/买卖盘口）"""
    symbol: str
    timestamp: datetime
    bid_prices: list[float] = field(default_factory=list)
    bid_volumes: list[int] = field(default_factory=list)
    ask_prices: list[float] = field(default_factory=list)
    ask_volumes: list[int] = field(default_factory=list)
    big_orders: list[dict[str, Any]] = field(default_factory=list)
    fund_inflow: float = 0.0
    fund_outflow: float = 0.0


@dataclass
class AgentReport:
    """Agent 分析报告"""
    agent: AgentName
    timestamp: datetime = field(default_factory=datetime.now)
    report_id: str = ""
    summary: str = ""
    status: ReportStatus = ReportStatus.OK
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    signals: list[dict[str, Any]] = field(default_factory=list)
    raw_source: str = ""

    def __post_init__(self):
        if not self.report_id:
            self.report_id = f"{self.agent.value}_{self.timestamp.isoformat()}"


@dataclass
class RiskOverride:
    """风控否决事件（Risk Agent 一票否决）"""
    reason: str
    action: str
    severity: str = "critical"
    timestamp: datetime = field(default_factory=datetime.now)
    source_agent: AgentName = AgentName.RISK


@dataclass
class Decision:
    """Chief Analyst 最终决策"""
    action: DecisionAction
    confidence: float
    reasoning: str
    evidence_sources: list[str] = field(default_factory=list)
    evidence_chain: dict[str, Any] = field(default_factory=dict)
    risk_override: Optional[RiskOverride] = None
    provider_label: str = "unknown"
    provider_status: ProviderStatus = ProviderStatus.HEALTHY
    timestamp: datetime = field(default_factory=datetime.now)
    decision_id: str = ""

    def __post_init__(self):
        if not self.decision_id:
            self.decision_id = f"decision_{self.timestamp.isoformat()}"


@dataclass
class SimilarCase:
    """历史相似案例"""
    case_id: str
    similarity_score: float
    decision: Optional[Decision] = None
    outcome: Optional[float] = None
    market_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class HeartbeatMessage:
    """心跳消息"""
    agent: AgentName
    timestamp: datetime = field(default_factory=datetime.now)
    status: str = "alive"
    uptime_seconds: float = 0.0


@dataclass
class SystemStatus:
    """系统整体状态（/health 响应）"""
    redis: str = "disconnected"
    agents: dict[str, bool] = field(default_factory=dict)
    active_llm_provider: str = "unknown"
    llm_provider_status: ProviderStatus = ProviderStatus.HEALTHY
    last_decision: Optional[datetime] = None
    uptime_seconds: float = 0.0

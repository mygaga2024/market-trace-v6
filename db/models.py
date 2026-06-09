"""
Market Trace V6.0 — ORM 模型
SQLAlchemy 异步模型：Agent 报告、最终决策、历史相似案例
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentReportModel(Base):
    """Agent 分析报告持久化"""

    __tablename__ = "agent_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), index=True, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<AgentReport agent={self.agent} id={self.report_id}>"


class DecisionModel(Base):
    """最终决策持久化"""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    evidence_sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    evidence_chain: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    risk_override: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    provider_label: Mapped[str] = mapped_column(String(64), default="unknown")
    provider_status: Mapped[str] = mapped_column(String(16), default="healthy")
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<Decision action={self.action} confidence={self.confidence}>"


class SimilarCaseModel(Base):
    """历史相似案例持久化（配合 core/memory.py 检索）"""

    __tablename__ = "similar_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    features: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    decision_action: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    outcome: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    market_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<SimilarCase id={self.case_id} score={self.similarity_score}>"


class WatchlistModel(Base):
    """持仓/关注股票列表"""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<Watchlist symbol={self.symbol} name={self.name}>"

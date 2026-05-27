"""
Market Trace V6.0 — 数据库模块
异步引擎 + 会话工厂 + CRUD 仓储 + 自动建表
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base, AgentReportModel, DecisionModel, SimilarCaseModel


class Database:
    """
    异步数据库管理器

    默认 SQLite (aiosqlite)，通过 config 中的数据库 URL 切换。
    提供仓储方法用于 Agent 报告的读写、决策持久化、案例管理。
    """

    def __init__(self, database_url: str = "sqlite+aiosqlite:///data/market_trace.db", echo: bool = False):
        self._url = database_url
        self._engine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init(self) -> None:
        """创建所有表"""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表已初始化: {}", self._url)

    async def close(self) -> None:
        """关闭引擎"""
        await self._engine.dispose()
        logger.info("数据库连接已关闭")

    async def session(self) -> AsyncIterator[AsyncSession]:
        """获取会话上下文管理器"""
        async with self._session_factory() as session:
            yield session

    # ---- Agent Report CRUD ----

    async def save_report(
        self,
        agent: str,
        report_id: str,
        summary: str = "",
        data: Optional[dict] = None,
        confidence: float = 0.0,
        status: str = "ok",
        symbol: Optional[str] = None,
    ) -> AgentReportModel:
        async with self._session_factory() as session:
            q = select(AgentReportModel).where(AgentReportModel.report_id == report_id)
            result = await session.execute(q)
            existing = result.scalar_one_or_none()

            if existing:
                existing.agent = agent
                existing.summary = summary
                existing.data = data
                existing.confidence = confidence
                existing.status = status
                existing.symbol = symbol
                existing.timestamp = datetime.now(timezone.utc)
            else:
                existing = AgentReportModel(
                    report_id=report_id,
                    agent=agent,
                    symbol=symbol,
                    summary=summary,
                    data=data,
                    confidence=confidence,
                    status=status,
                )
                session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return existing

    async def get_latest_report(self, agent: str, symbol: Optional[str] = None) -> Optional[AgentReportModel]:
        async with self._session_factory() as session:
            q = select(AgentReportModel).where(AgentReportModel.agent == agent)
            if symbol:
                q = q.where(AgentReportModel.symbol == symbol)
            q = q.order_by(AgentReportModel.timestamp.desc()).limit(1)
            result = await session.execute(q)
            return result.scalar_one_or_none()

    async def get_reports(
        self, agent: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> list[AgentReportModel]:
        async with self._session_factory() as session:
            q = select(AgentReportModel)
            if agent:
                q = q.where(AgentReportModel.agent == agent)
            q = q.order_by(AgentReportModel.timestamp.desc()).limit(limit).offset(offset)
            result = await session.execute(q)
            return list(result.scalars().all())

    # ---- Decision CRUD ----

    async def save_decision(
        self,
        decision_id: str,
        action: str,
        confidence: float,
        reasoning: str = "",
        evidence_sources: Optional[list] = None,
        evidence_chain: Optional[dict] = None,
        risk_override: Optional[dict] = None,
        provider_label: str = "unknown",
        provider_status: str = "healthy",
    ) -> DecisionModel:
        async with self._session_factory() as session:
            model = DecisionModel(
                decision_id=decision_id,
                action=action,
                confidence=confidence,
                reasoning=reasoning,
                evidence_sources=evidence_sources or [],
                evidence_chain=evidence_chain or {},
                risk_override=risk_override,
                provider_label=provider_label,
                provider_status=provider_status,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def get_latest_decision(self) -> Optional[DecisionModel]:
        async with self._session_factory() as session:
            q = select(DecisionModel).order_by(DecisionModel.timestamp.desc()).limit(1)
            result = await session.execute(q)
            return result.scalar_one_or_none()

    async def get_decisions(self, limit: int = 20, offset: int = 0) -> list[DecisionModel]:
        async with self._session_factory() as session:
            q = select(DecisionModel).order_by(DecisionModel.timestamp.desc()).limit(limit).offset(offset)
            result = await session.execute(q)
            return list(result.scalars().all())

    async def get_decision_stats(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            total_q = select(func.count(DecisionModel.id))
            total = (await session.execute(total_q)).scalar() or 0

            actions = {}
            for action_val in ["BUY", "SELL", "HOLD", "WAIT"]:
                q = select(func.count(DecisionModel.id)).where(DecisionModel.action == action_val)
                actions[action_val] = (await session.execute(q)).scalar() or 0

            avg_conf_q = select(func.avg(DecisionModel.confidence))
            avg_conf = (await session.execute(avg_conf_q)).scalar()

            return {
                "total": int(total),
                "action_distribution": {k: int(v) for k, v in actions.items()},
                "avg_confidence": round(float(avg_conf or 0), 4),
            }

    # ---- Similar Case CRUD ----

    async def save_case(
        self,
        case_id: str,
        features: Optional[list[float]] = None,
        decision_action: Optional[str] = None,
        outcome: Optional[float] = None,
        similarity_score: float = 0.0,
        market_context: Optional[dict] = None,
    ) -> SimilarCaseModel:
        async with self._session_factory() as session:
            model = SimilarCaseModel(
                case_id=case_id,
                features=features,
                decision_action=decision_action,
                outcome=outcome,
                similarity_score=similarity_score,
                market_context=market_context or {},
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def get_cases(self, limit: int = 100) -> list[SimilarCaseModel]:
        async with self._session_factory() as session:
            q = select(SimilarCaseModel).order_by(SimilarCaseModel.timestamp.desc()).limit(limit)
            result = await session.execute(q)
            return list(result.scalars().all())

    async def get_case_statistics(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            total_q = select(func.count(SimilarCaseModel.id))
            total = (await session.execute(total_q)).scalar() or 0

            outcome_q = select(func.avg(SimilarCaseModel.outcome)).where(SimilarCaseModel.outcome.isnot(None))
            avg_outcome = (await session.execute(outcome_q)).scalar()

            win_q = select(func.count(SimilarCaseModel.id)).where(SimilarCaseModel.outcome > 0)
            wins = (await session.execute(win_q)).scalar() or 0

            return {
                "total": int(total),
                "avg_outcome": round(float(avg_outcome or 0), 4),
                "win_rate": round(wins / max(total, 1), 4),
            }

"""
Market Trace V6.0 — Macro Agent
宏观政策预期、板块轮动、市场风险偏好指数评估
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from agents.base_agent import BaseAgent
from core.bus import MessageBus
from core.schema import AgentReport, AgentName, ReportStatus
from data_provider.akshare_impl import AkShareProvider


class MacroAgent(BaseAgent):
    """
    宏观分析 Agent

    定时拉取宏观数据，计算市场风险偏好指数 (Risk Appetite Index, RAI)。
    RAI ∈ [0, 1]，值越高表示市场风险偏好越高（看多），越低表示避险情绪浓厚（看空）。
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict[str, Any],
        data_provider: Optional[AkShareProvider] = None,
        db=None,
    ):
        super().__init__(AgentName.MACRO.value, bus, ["events:data"], config, db=db)

        agent_cfg = config.get("agents", {}).get("macro", {})
        self._interval: int = agent_cfg.get("interval", 600)
        self._indices: list[str] = agent_cfg.get("indices", ["sh000001", "sz399001", "sz399006"])

        self._provider = data_provider
        self._last_report: Optional[AgentReport] = None

    async def run(self) -> None:
        """主循环：定时拉取宏观数据并生成报告"""
        await asyncio.sleep(5)

        while self._running:
            try:
                await self._fetch_and_report()
            except Exception as e:
                logger.error("Macro Agent 数据拉取失败: {}", e)

            await asyncio.sleep(self._interval)

    async def process_message(self, message: dict[str, Any]) -> None:
        pass

    async def _fetch_and_report(self) -> None:
        logger.info("Macro Agent 开始拉取宏观数据...")

        macro_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "macro_agent",
        }

        rai_components: dict[str, float] = {}

        if self._provider:
            raw = await self._provider.fetch_macro_indices()
            if raw:
                macro_data["raw"] = raw
                rai_components = self._calculate_rai(raw)

        rai = self._compute_rai_score(rai_components)
        macro_data["risk_appetite_index"] = rai
        macro_data["components"] = rai_components

        interpretation = self._interpret_rai(rai)
        macro_data["interpretation"] = interpretation

        report = AgentReport(
            agent=AgentName.MACRO,
            timestamp=datetime.now(timezone.utc),
            summary=f"RAI={rai:.2f} ({interpretation['regime']})",
            status=ReportStatus.OK,
            data=macro_data,
            confidence=abs(rai - 0.5) * 2,
        )

        self._last_report = report

        await self.publish("reports:macro", {
            "event": "MACRO_REPORT",
            "report_id": report.report_id,
            "agent": report.agent.value,
            "summary": report.summary,
            "data": report.data,
            "confidence": report.confidence,
            "timestamp": report.timestamp.isoformat(),
        })

        logger.info("Macro Agent 报告已发布: RAI={:.2f} {}", rai, interpretation["regime"])

        if self.db:
            try:
                await self.db.save_report(
                    report_id=report.report_id, agent=report.agent.value,
                    summary=report.summary, data=report.data,
                    confidence=report.confidence, status=report.status.value,
                )
            except Exception as e:
                logger.warning("Macro Agent 报告保存DB失败: {}", e)

    def _calculate_rai(self, raw: dict[str, Any]) -> dict[str, float]:
        """根据宏观数据计算 RAI 各分项"""
        components: dict[str, float] = {}

        try:
            indices = raw.get("indices", [])
            if indices:
                components["index_breadth"] = self._calc_breadth(indices)
        except Exception as e:
            logger.debug("RAI breadth 计算失败: {}", e)
            components["index_breadth"] = 0.5

        try:
            sectors = raw.get("sectors", [])
            if sectors:
                components["sector_momentum"] = self._calc_sector_momentum(sectors)
        except Exception as e:
            logger.debug("RAI sector 计算失败: {}", e)
            components["sector_momentum"] = 0.5

        if "index_breadth" not in components:
            components["index_breadth"] = 0.5
        if "sector_momentum" not in components:
            components["sector_momentum"] = 0.5

        return components

    @staticmethod
    def _calc_breadth(indices: list[dict]) -> float:
        """涨跌比 → [0,1]: >0.5 上涨居多"""
        up = sum(1 for i in indices if float(i.get("涨跌幅", 0) or 0) > 0)
        total = len(indices)
        if total == 0:
            return 0.5
        return min(1.0, max(0.0, up / total))

    @staticmethod
    def _calc_sector_momentum(sectors: list[dict]) -> float:
        """板块动量 → [0,1]"""
        up = sum(1 for s in sectors if float(s.get("涨跌幅", 0) or 0) > 0)
        total = len(sectors)
        if total == 0:
            return 0.5
        return min(1.0, max(0.0, up / total))

    @staticmethod
    def _compute_rai_score(components: dict[str, float]) -> float:
        """加权合成 RAI ∈ [0, 1]"""
        if not components:
            return 0.5

        has_sectors = "sector_momentum" in components
        if has_sectors:
            weights = {"index_breadth": 0.6, "sector_momentum": 0.4}
        else:
            weights = {"index_breadth": 1.0}

        score = sum(components.get(k, 0.5) * w for k, w in weights.items())
        return round(min(1.0, max(0.0, score)), 4)

    @staticmethod
    def _interpret_rai(rai: float) -> dict[str, str]:
        """解释 RAI 数值"""
        if rai >= 0.7:
            regime = "极度乐观 - 追高风险大"
            bias = "bullish"
        elif rai >= 0.55:
            regime = "温和乐观 - 震荡偏多"
            bias = "slightly_bullish"
        elif rai >= 0.45:
            regime = "中性 - 方向不明"
            bias = "neutral"
        elif rai >= 0.3:
            regime = "温和悲观 - 震荡偏空"
            bias = "slightly_bearish"
        else:
            regime = "极度悲观 - 恐慌机会"
            bias = "bearish"
        return {"regime": regime, "bias": bias}

    @property
    def last_report(self) -> Optional[AgentReport]:
        return self._last_report

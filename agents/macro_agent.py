"""
Market Trace V6.0 — Macro Agent
宏观政策预期、板块轮动、市场风险偏好指数评估
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
        raw: Optional[dict[str, Any]] = None

        if self._provider:
            raw = await self._provider.fetch_macro_indices()

        if raw:
            macro_data["raw"] = raw
            # 指数历史 K 线（近一年）用于计算位置因子；失败/无数据时该因子不参与合成
            klines = await self._fetch_index_klines(raw.get("indices", []))
            rai_components = self._calculate_rai(raw, klines)

        rai = self._compute_rai_score(rai_components)
        macro_data["risk_appetite_index"] = rai
        macro_data["components"] = rai_components

        position = rai_components.get("position")
        interpretation = self._interpret_rai(rai, position)
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

    async def _fetch_index_klines(self, indices: list[dict]) -> dict[str, list]:
        """拉取指数近一年日 K，用于位置因子；仅取前 3 个指数控制耗时"""
        if not self._provider or not indices:
            return {}
        klines: dict[str, list] = {}
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
        for idx in indices[:3]:
            code = idx.get("code") or idx.get("symbol")
            if not code:
                continue
            try:
                bars = await self._provider.fetch_kline(code, start, end, "daily")
                if bars:
                    klines[code] = bars
                    logger.info("指数 {} 位置因子 K 线: {} 条", code, len(bars))
            except Exception as e:
                logger.debug("指数 {} 位置因子 K 线获取失败: {}", code, e)
        return klines

    def _calculate_rai(self, raw: dict[str, Any], klines: Optional[dict[str, list]] = None) -> dict[str, float]:
        """根据宏观数据计算 RAI 各分项；缺失因子不写入，合成时按可用因子动态加权"""
        components: dict[str, float] = {}

        try:
            indices = raw.get("indices", [])
            if indices:
                components["index_breadth"] = self._calc_breadth(indices)
        except Exception as e:
            logger.debug("RAI breadth 计算失败: {}", e)

        try:
            sectors = raw.get("sectors", [])
            if sectors:
                components["sector_momentum"] = self._calc_sector_momentum(sectors)
        except Exception as e:
            logger.debug("RAI sector 计算失败: {}", e)

        if klines:
            try:
                position = self._calc_position(raw.get("indices", []), klines)
                if position is not None:
                    components["position"] = position
            except Exception as e:
                logger.debug("RAI position 计算失败: {}", e)

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
    def _calc_position(indices: list[dict], klines: dict[str, list]) -> Optional[float]:
        """
        指数位置因子 ∈ [0,1]: 0=近一年最低, 1=近一年最高, 0.5=中位
        单指数 = 0.7×近一年高低分位 + 0.3×站上/跌破 MA20 的强度
        低位反弹时该值偏低, 可抑制"追高风险大"的误判。
        """
        if not klines:
            return None
        positions: list[float] = []
        for idx in indices:
            code = idx.get("code") or idx.get("symbol")
            if not code:
                continue
            bars = klines.get(code)
            if not bars or len(bars) < 20:
                continue
            closes = [float(b.close) for b in bars]
            if len(closes) < 20:
                continue
            close = closes[-1]
            hi = max(closes[-250:])
            lo = min(closes[-250:])
            pct = 0.5 if hi == lo else (close - lo) / (hi - lo)
            ma20 = sum(closes[-20:]) / 20
            ma_pos = min(1.0, max(0.0, 0.5 + (close / ma20 - 1) * 2))
            positions.append(0.7 * pct + 0.3 * ma_pos)
        if not positions:
            return None
        return round(sum(positions) / len(positions), 4)

    @staticmethod
    def _compute_rai_score(components: dict[str, float]) -> float:
        """
        加权合成 RAI ∈ [0, 1]
        仅对实际可用的因子加权: breadth 0.4 / sector 0.3 / position 0.3
        (缺失因子自动重分配, 不再用 0.5 兜底参与合成——修复无数据稀释问题)
        """
        valid = {k: v for k, v in components.items() if v is not None}
        if not valid:
            return 0.5

        has_b = "index_breadth" in valid
        has_s = "sector_momentum" in valid
        has_p = "position" in valid

        if has_b and has_s and has_p:
            weights = {"index_breadth": 0.4, "sector_momentum": 0.3, "position": 0.3}
        elif has_b and has_s:
            weights = {"index_breadth": 0.6, "sector_momentum": 0.4}
        elif has_b and has_p:
            weights = {"index_breadth": 0.6, "position": 0.4}
        elif has_s and has_p:
            weights = {"sector_momentum": 0.5, "position": 0.5}
        elif has_b:
            weights = {"index_breadth": 1.0}
        elif has_s:
            weights = {"sector_momentum": 1.0}
        else:
            weights = {"position": 1.0}

        score = sum(valid.get(k, 0.5) * w for k, w in weights.items())
        return round(min(1.0, max(0.0, score)), 4)

    @staticmethod
    def _interpret_rai(rai: float, position: Optional[float] = None) -> dict[str, str]:
        """解释 RAI 数值；提供 position 时结合市场位置避免误判

        低位 + 高 RAI → 低位强势反弹(右侧机会)而非"追高风险大"
        高位 + 低 RAI → 高位走弱(警惕回落)而非单纯"恐慌"
        """
        if position is not None:
            if rai >= 0.7 and position < 0.45:
                return {"regime": "低位强势反弹 - 右侧机会", "bias": "bullish"}
            if rai <= 0.3 and position > 0.55:
                return {"regime": "高位走弱 - 警惕回落", "bias": "bearish"}

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

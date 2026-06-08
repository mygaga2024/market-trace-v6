"""
Market Trace V6.0 — LLM 接口工厂与多级回退链
OpenAI 兼容接口 + 链式回退路由 (DeepSeek → Gemini → MiniMax → 纯规则)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from loguru import logger

from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from core.schema import AgentReport, Decision, DecisionAction, ProviderStatus, AgentName


class LLMInterface(ABC):
    """LLM 调用抽象接口"""

    def __init__(self, provider_name: str, config: dict[str, Any]):
        self.provider_name = provider_name
        self.model: str = config.get("model", "unknown")
        self.timeout: float = config.get("timeout", 60.0)
        self.max_retries: int = config.get("max_retries", 2)
        self.temperature: float = config.get("temperature", 0.3)
        self.max_tokens: int = config.get("max_tokens", 2048)

    @abstractmethod
    async def analyze(self, reports: dict[str, AgentReport]) -> Decision:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...


class OpenAICompatibleLLM(LLMInterface):
    """
    OpenAI 兼容格式的 LLM 客户端

    兼容 DeepSeek、Gemini (OpenAI endpoint)、MiniMax 等任何
    提供 OpenAI-compatible /v1/chat/completions 接口的供应商。
    """

    def __init__(
        self,
        provider_name: str,
        config: dict[str, Any],
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        super().__init__(provider_name, config)
        self.api_key: str = config.get("api_key", "")
        self.base_url: str = config.get("base_url", "").rstrip("/")
        self._cb = circuit_breaker or CircuitBreaker(name=f"llm:{provider_name}")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
            )
        return self._client

    async def analyze(self, reports: dict[str, AgentReport]) -> Decision:
        prompt = self._build_prompt(reports)

        async def _call():
            return await self._chat_completion(prompt)

        async def _fallback():
            raise RuntimeError(f"LLM [{self.provider_name}] 熔断中，无法调用")

        try:
            result = await self._cb.call(_call, fallback=_fallback)
            decision = self._parse_decision(result, reports)
            decision.provider_label = f"{self.provider_name}:{self.model}"
            decision.provider_status = ProviderStatus.HEALTHY
            return decision
        except Exception as e:
            logger.error("LLM [{}] 分析失败: {}", self.provider_name, e)
            raise

    async def _chat_completion(self, system_prompt: str) -> dict[str, Any]:
        """调用 OpenAI 兼容的 /v1/chat/completions"""
        client = await self._get_client()
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个专业的量化交易决策分析师。只输出JSON，不输出其他内容。"},
                {"role": "user", "content": system_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                result = json.loads(content)
                logger.info("LLM [{}] 调用成功 ({} tokens)", self.provider_name, data.get("usage", {}).get("total_tokens", "?"))
                return result
            except httpx.TimeoutException:
                logger.warning("LLM [{}] 超时 (尝试 {}/{})", self.provider_name, attempt + 1, self.max_retries + 1)
                if attempt >= self.max_retries:
                    raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("LLM [{}] 限频 429 (尝试 {}/{})", self.provider_name, attempt + 1, self.max_retries + 1)
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                elif e.response.status_code >= 500:
                    logger.warning("LLM [{}] 服务端错误 {} (尝试 {}/{})", self.provider_name, e.response.status_code, attempt + 1, self.max_retries + 1)
                else:
                    logger.error("LLM [{}] HTTP {}: {}", self.provider_name, e.response.status_code, e.response.text[:300])
                    raise
            except (json.JSONDecodeError, KeyError) as e:
                logger.error("LLM [{}] 响应解析失败: {}", self.provider_name, e)
                if attempt >= self.max_retries:
                    raise RuntimeError(f"LLM [{self.provider_name}] 响应解析失败: {e}")

        raise RuntimeError(f"LLM [{self.provider_name}] 所有重试均失败")

    def _build_prompt(self, reports: dict[str, AgentReport]) -> str:
        """构建决策分析提示词"""
        parts = [f"当前时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"]
        parts.append("请根据以下多维度分析报告，输出一个JSON格式的交易决策。\n")

        macro = reports.get("macro")
        if macro and macro.data:
            rai = macro.data.get("risk_appetite_index", 0.5)
            interp = macro.data.get("interpretation", {})
            components = macro.data.get("components", {})
            parts.append("## 宏观报告")
            parts.append(f"- 风险偏好指数(RAI): {rai:.2f}")
            parts.append(f"- 市场状态: {interp.get('regime', '未知')}")
            parts.append(f"- 偏向: {interp.get('bias', 'neutral')}")
            parts.append(f"- 涨跌比: {components.get('index_breadth', 'N/A')}")
            parts.append(f"- 板块动量: {components.get('sector_momentum', 'N/A')}")
            parts.append("")

        signal = reports.get("signal")
        if signal and signal.data:
            indicators = signal.data.get("indicators", {})
            signals = signal.data.get("signals", [])
            parts.append("## 技术信号报告")
            if indicators.get("macd"):
                m = indicators["macd"]
                parts.append(f"- MACD: DIF={m['dif']:.4f}, DEA={m['dea']:.4f}, 柱={m['histogram']:.4f}")
            if indicators.get("rsi") is not None:
                parts.append(f"- RSI: {indicators['rsi']:.2f}")
            if signals:
                parts.append("- 检测信号:")
                for s in signals:
                    parts.append(f"  * {s['type']} ({s['direction']}, 强度={s.get('strength', 'N/A')})")
            parts.append(f"- 可靠性评分: {signal.data.get('reliability', 0.5):.2f}")
            parts.append("")

        trace = reports.get("trace")
        if trace and trace.data:
            t_signals = trace.data.get("signals", [])
            flow = trace.data.get("fund_flow", {})
            parts.append("## 资金痕迹报告")
            if flow:
                parts.append(f"- 主力净流入: {flow.get('main_net_inflow', 0)/1e4:.0f}万 ({flow.get('main_net_inflow_pct', 0):.2f}%)")
                parts.append(f"- 超大单净额: {flow.get('super_large_net', 0)/1e4:.0f}万")
            if t_signals:
                parts.append("- 异动信号:")
                for s in t_signals:
                    parts.append(f"  * {s['type']} ({s['direction']}, 强度={s.get('strength', 'N/A')})")
            parts.append(f"- 资金方向: {trace.data.get('direction', 'neutral')}")
            parts.append("")

        parts.append("""
## 决策框架（四维投票制）

请按以下框架评分并输出决策：

### 1. 宏观环境打分(0-10, 权重30%)
- RAI > 0.55 → 7-10分；RAI 0.45-0.55 → 4-6分；RAI < 0.45 → 1-3分

### 2. 技术面打分(0-10, 权重40%)
- RSI < 30 → +3 (超卖反弹)；30-70 → 0；> 70 → -3 (超买回调)
- MACD 金叉(DIF上穿DEA) → +2；死叉 → -2
- 收盘价在 MA5 上方 → +1；MA5在MA20上方(多头排列) → +2

### 3. 资金面打分(0-10, 权重30%)
- 量比 > 2 → +3；0.5-2 → 0；< 0.5 → -2
- 资金方向 bullish → +3；bearish → -3
- 大单异动信号 ≥ 2个 → +2

### 4. 综合决策
- 加权总分 > 6.5 → BUY；4.0-6.5 → HOLD；< 4.0 → SELL
- RAI < 0.25 或 > 0.75 时 → 最高只允许 HOLD，不允许 BUY
- 两个以上指标矛盾时 → 置信度降低 0.2

输出JSON格式：
- action: "BUY" | "SELL" | "HOLD" | "WAIT"
- confidence: 置信度 0.0-1.0
- reasoning: 详细推理(中文，200字以内，包含宏观/技术/资金三维评分)
- key_insights: 关键洞察(最多3条)
""")
        return "\n".join(parts)

    def _parse_decision(self, llm_result: dict, reports: dict[str, AgentReport]) -> Decision:
        """解析 LLM 响应为 Decision"""
        action_str = (llm_result.get("action") or "WAIT").upper()
        try:
            action = DecisionAction(action_str)
        except ValueError:
            action = DecisionAction.WAIT

        evidence = list(reports.keys())

        default_report = AgentReport(agent=AgentName.MACRO)

        return Decision(
            action=action,
            confidence=float(llm_result.get("confidence", 0.5)),
            reasoning=str(llm_result.get("reasoning", "LLM 分析完成")),
            evidence_sources=evidence,
            evidence_chain={
                "macro_report_id": reports["macro"].report_id if "macro" in reports else default_report.report_id,
                "signal_report_id": reports["signal"].report_id if "signal" in reports else default_report.report_id,
                "trace_report_id": reports["trace"].report_id if "trace" in reports else default_report.report_id,
                "key_insights": llm_result.get("key_insights", []),
                "raw_llm_response": llm_result,
            },
            provider_label=f"{self.provider_name}:{self.model}",
            provider_status=ProviderStatus.HEALTHY,
        )

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            url = f"{self.base_url}/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = await client.get(url, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class RuleBasedAnalyzer(LLMInterface):
    """
    纯规则加权决策（LLM 全部不可用时的终极退化）

    使用配置中的固定权重矩阵对各 Agent 报告进行加权评分，
    输出确定性决策（不依赖任何外部服务）。
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__("rule_based", config)
        weights = config.get("weights", {
            "macro": 0.25, "signal": 0.25, "trace": 0.30, "risk": 0.20,
        })
        self.weights = weights

    async def analyze(self, reports: dict[str, AgentReport]) -> Decision:
        logger.warning("所有 LLM 不可用，使用纯规则加权决策")

        score = 0.0
        evidence = list(reports.keys())
        insights: list[str] = []

        if "macro" in reports and reports["macro"].data:
            rai = reports["macro"].data.get("risk_appetite_index", 0.5)
            bias = reports["macro"].data.get("interpretation", {}).get("bias", "neutral")
            macro_score = (rai - 0.5) * 2
            score += macro_score * self.weights.get("macro", 0.25)
            insights.append(f"宏观RAI={rai:.2f}({bias})")

        if "signal" in reports and reports["signal"].data:
            signals = reports["signal"].data.get("signals", [])
            bull = sum(s.get("strength", 0) for s in signals if s["direction"] == "bullish")
            bear = sum(s.get("strength", 0) for s in signals if s["direction"] == "bearish")
            signal_score = (bull - bear) / max(bull + bear, 1)
            score += signal_score * self.weights.get("signal", 0.25)
            insights.append(f"技术信号: 多{bull:.1f}/空{bear:.1f}")

        if "trace" in reports and reports["trace"].data:
            t_signals = reports["trace"].data.get("signals", [])
            bull = sum(s.get("strength", 0) for s in t_signals if s["direction"] == "bullish")
            bear = sum(s.get("strength", 0) for s in t_signals if s["direction"] == "bearish")
            trace_score = (bull - bear) / max(bull + bear, 1)
            score += trace_score * self.weights.get("trace", 0.30)
            insights.append(f"资金痕迹: 多{bull:.1f}/空{bear:.1f}")

        # Risk 报告补充评分（如果存在）
        if "risk" in reports and reports["risk"].data:
            risk_data = reports["risk"].data
            risk_severity = risk_data.get("severity", "normal")
            if risk_severity == "critical":
                risk_score = -1.0
            elif risk_severity == "warning":
                risk_score = -0.5
            else:
                risk_score = 0.0
            score += risk_score * self.weights.get("risk", 0.20)
            if risk_severity != "normal":
                insights.append(f"风控: {risk_severity}")

        action = DecisionAction.HOLD
        if score > 0.3:
            action = DecisionAction.BUY
        elif score < -0.3:
            action = DecisionAction.SELL
        elif abs(score) < 0.1:
            action = DecisionAction.WAIT

        confidence = abs(score)

        return Decision(
            action=action,
            confidence=round(confidence, 4),
            reasoning=f"纯规则加权评分={score:.4f}，权重={self.weights}",
            evidence_sources=evidence,
            evidence_chain={"score": score, "weights": self.weights, "insights": insights},
            provider_label="rule_based:fallback",
            provider_status=ProviderStatus.FALLBACK,
        )

    async def health_check(self) -> bool:
        return True


class LLMFallbackChain:
    """
    LLM 多级回退链 (Chain of Responsibility)

    调用顺序：
    1. primary (DeepSeek) → 成功则返回
    2. primary 熔断/失败 → secondary (Gemini) → 成功则返回
    3. secondary 熔断/失败 → tertiary (MiniMax) → 成功则返回
    4. 全部不可用 → RuleBasedAnalyzer 纯规则降级
    """

    def __init__(
        self,
        primary: OpenAICompatibleLLM,
        secondary: OpenAICompatibleLLM,
        tertiary: OpenAICompatibleLLM,
        rule_based: RuleBasedAnalyzer,
    ):
        self.providers = [primary, secondary, tertiary]
        self.rule_based = rule_based
        self._active_provider: Optional[str] = None

    @property
    def active_provider(self) -> str:
        return self._active_provider or "none"

    async def analyze(self, reports: dict[str, AgentReport]) -> Decision:
        for i, provider in enumerate(self.providers):
            tier = ["主力", "备用", "三级兜底"][i]
            try:
                logger.info("尝试 LLM [{}] ({}): {}", provider.provider_name, tier, provider.model)
                decision = await provider.analyze(reports)
                self._active_provider = provider.provider_name
                logger.info("LLM 决策成功: provider={}", self._active_provider)
                return decision
            except CircuitBreakerOpenError as e:
                logger.warning("LLM [{}] 熔断: {}", provider.provider_name, e)
                continue
            except Exception as e:
                logger.error("LLM [{}] 调用失败: {}", provider.provider_name, e)
                continue

        logger.critical("所有 LLM 不可用，执行纯规则降级")
        decision = await self.rule_based.analyze(reports)
        self._active_provider = "rule_based"
        return decision

    async def health_check(self) -> dict[str, bool]:
        results = {}
        for p in self.providers:
            results[p.provider_name] = await p.health_check()
        results["rule_based"] = True
        return results

    async def close(self) -> None:
        """关闭所有 LLM provider 的连接池"""
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass

"""
Market Trace V6.0 — 相似历史案例库
特征向量 + 余弦相似度快速检索，供 Agent 查询历史胜率
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
from loguru import logger

from core.schema import SimilarCase


class CaseMemory:
    """
    历史案例库

    使用轻量级特征向量 + 余弦相似度检索，
    避免引入大型向量数据库，适合单容器 ≤ 1GB 内存约束。
    """

    def __init__(self, max_cases: int = 10000):
        self._cases: list[SimilarCase] = []
        self._vectors: list[np.ndarray] = []
        self._max_cases = max_cases
        self._case_counter = 0

    def add_case(
        self,
        features: list[float],
        decision: dict[str, Any],
        outcome: Optional[float] = None,
        market_context: Optional[dict[str, Any]] = None,
    ) -> SimilarCase:
        """添加新案例"""
        vec = np.array(features, dtype=np.float64)

        self._case_counter += 1
        case = SimilarCase(
            case_id=f"case_{self._case_counter}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            similarity_score=1.0,
            decision=None,
            outcome=outcome,
            market_context=market_context or {},
        )

        self._cases.append(case)
        self._vectors.append(vec)

        if len(self._cases) > self._max_cases:
            self._cases.pop(0)
            self._vectors.pop(0)

        logger.debug("案例库新增: {} | 总案例数: {}", case.case_id, len(self._cases))
        return case

    def find_similar(
        self, query_features: list[float], k: int = 5
    ) -> list[SimilarCase]:
        """
        查找最相似的 k 个历史案例

        Args:
            query_features: 查询特征向量
            k: 返回最相似的前 k 个

        Returns:
            按相似度降序排列的案例列表
        """
        if not self._vectors or k <= 0:
            return []

        query = np.array(query_features, dtype=np.float64)

        if len(query) == 0:
            return []

        similarity_scores = self._batch_cosine_similarity(query, self._vectors)

        top_k_indices = np.argsort(similarity_scores)[::-1][:k]
        top_k_indices = top_k_indices[similarity_scores[top_k_indices] > 0.3]

        results: list[SimilarCase] = []
        for idx in top_k_indices:
            idx = int(idx)
            case = self._cases[idx]
            case.similarity_score = float(similarity_scores[idx])
            results.append(case)

        logger.debug("案例检索: k={} → 命中 {} 条", k, len(results))
        return results

    @staticmethod
    def _batch_cosine_similarity(query: np.ndarray, vectors: list[np.ndarray]) -> np.ndarray:
        """批量计算余弦相似度"""
        if not vectors:
            return np.array([])

        mat = np.vstack(vectors)
        query_norm = np.linalg.norm(query)
        mat_norm = np.linalg.norm(mat, axis=1)

        mask = (query_norm > 1e-12) & (mat_norm > 1e-12)
        similarities = np.zeros(len(vectors))

        if np.any(mask):
            dot = np.dot(mat[mask], query)
            similarities[mask] = dot / (mat_norm[mask] * query_norm)

        similarities = np.clip(similarities, 0.0, 1.0)
        return similarities

    def get_statistics(self) -> dict[str, Any]:
        """获取案例库统计信息"""
        outcomes = [c.outcome for c in self._cases if c.outcome is not None]
        return {
            "total_cases": len(self._cases),
            "cases_with_outcome": len(outcomes),
            "avg_outcome": float(np.mean(outcomes)) if outcomes else None,
            "win_rate": float(np.mean([1 if o and o > 0 else 0 for o in outcomes])) if outcomes else None,
        }

    def clear(self) -> None:
        """清空案例库"""
        self._cases.clear()
        self._vectors.clear()
        self._case_counter = 0
        logger.info("案例库已清空")

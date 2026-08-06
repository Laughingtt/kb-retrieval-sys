"""检索接口层 —— M2 设计 §5.1。

Retriever ABC + SearchHit + RRFFuser。P0 仅注册 BM25Retriever，fuse([bm25]) 单路
直通（去重 + 截断）。向量化后注册 VectorRetriever 即两路，契约不变。
吸收 llm_wiki RRF k=60。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = ["SearchHit", "Retriever", "RRFFuser"]


@dataclass
class SearchHit:
    doc_id: str
    section_id: str
    title: str
    snippet: str = ""
    score: float = 0.0
    source: str = "bm25"


class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, top_n: int = 50) -> list[SearchHit]:
        ...


class RRFFuser:
    def fuse(self, results: list[list[SearchHit]], k: int = 60, top_k: int = 10) -> list[SearchHit]:
        """RRF: score = Σ 1/(k + rank_i)，rank_i 从 1 起。同 (doc_id, section_id) 取最高分合并。"""
        if not results:
            return []
        merged: dict[tuple[str, str], SearchHit] = {}
        for lane in results:
            for rank, hit in enumerate(lane, start=1):
                key = (hit.doc_id, hit.section_id)
                rrf = 1.0 / (k + rank)
                if key not in merged:
                    merged[key] = SearchHit(
                        doc_id=hit.doc_id, section_id=hit.section_id,
                        title=hit.title, snippet=hit.snippet,
                        score=rrf, source=hit.source,
                    )
                else:
                    merged[key].score += rrf
        ranked = sorted(merged.values(), key=lambda h: h.score, reverse=True)
        return ranked[:top_k]

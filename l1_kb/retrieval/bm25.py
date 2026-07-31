"""BM25 检索器 —— M2 设计 §5.3。

rank-bm25 BM25Okapi（IDF + 文档长度归一，真 BM25，不照搬 llm_wiki 手写打分）。
文档单元文本 = frontmatter title + section 标题 + 正文。纯内存，每次运行重建。
"""

from __future__ import annotations

from rank_bm25 import BM25Okapi

from .base import Retriever, SearchHit
from .tokenizer import tokenize

__all__ = ["BM25Retriever"]


class BM25Retriever(Retriever):
    def __init__(self, entries: list[dict]) -> None:
        """entries: [{slug, section_id, title, body_text}]，每个 entry 一个 corpus 文档。"""
        self._meta = entries
        self._corpus = [tokenize(f"{e['title']} {e['body_text']}") for e in entries]
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(self, query: str, top_n: int = 50) -> list[SearchHit]:
        if self._bm25 is None or not query.strip():
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_n]
        hits: list[SearchHit] = []
        for idx, sc in ranked:
            # 仅当该文档对查询词项有词频命中才产出（小语料下 BM25Okapi IDF 可能为 0/负，
            # 故不能用 score>0 过滤；用词频判定是否召回）。
            if not any(self._bm25.doc_freqs[idx].get(q) for q in q_tokens):
                continue
            e = self._meta[idx]
            hits.append(SearchHit(
                doc_id=e["slug"], section_id=e["section_id"],
                title=e["title"], snippet="",
                score=float(sc), source="bm25",
            ))
        return hits

"""L1 只读 service —— BM25 + RRF + snippet（下沉自 cli/kb.py:search）。

纯函数，供 service 路由与 CLI 复用（DRY）。
"""

from __future__ import annotations

from l1_kb.retrieval.base import SearchHit, RRFFuser
from l1_kb.retrieval.bm25 import BM25Retriever
from l1_kb.retrieval.snippet import make_snippet
from l1_kb.service.store import WikiStore

__all__ = ["search"]

_SNIPPET_MAX = 500
_TOP_N_PRE = 50
_RRF_K = 60


def search(store: WikiStore, query: str, top_k: int = 10) -> list[SearchHit]:
    """对 store 跑 BM25 + RRF，返回 top_k SearchHit。无命中返回 []。"""
    entries: list[dict] = []
    lines: dict[tuple[str, str], tuple[int, int]] = {}
    for page in store.pages:
        for s in page.sections:
            key = (page.slug, s.section_id)
            entries.append({
                "slug": page.slug,
                "section_id": s.section_id,
                "title": s.title or page.title,
                "body_text": s.body,
                "_text": page.raw,
                "_line_start": s.line_start,
                "_line_end": s.line_end,
            })
            lines[key] = (s.line_start, s.line_end)
    if not entries:
        return []
    bm25 = BM25Retriever(entries)
    hits = bm25.search(query, top_n=_TOP_N_PRE)
    fused = RRFFuser().fuse([hits], k=_RRF_K, top_k=top_k)
    out: list[SearchHit] = []
    for h in fused:
        page = store.by_slug.get(h.doc_id)
        if page is None:
            continue
        ls, le = lines.get((h.doc_id, h.section_id), (0, 0))
        snippet = make_snippet(page.raw, ls, le, max_chars=_SNIPPET_MAX) if ls else h.snippet
        out.append(SearchHit(
            doc_id=h.doc_id, section_id=h.section_id,
            title=h.title, snippet=snippet,
            score=h.score, source=h.source,
        ))
    return out

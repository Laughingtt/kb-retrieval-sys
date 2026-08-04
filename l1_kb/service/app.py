"""L1 只读 REST API —— FastAPI 6 个 GET 端点。无写/执行路由（硬约束 2）。

启动：uvicorn l1_kb.service.app:app  或  kb-serve
"""

from __future__ import annotations

import re

import l1_kb.config as config
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from l1_kb.ingest.wiki.index_log import _collect_pages
from l1_kb.ingest.wiki.page_types import PAGE_TYPES
from l1_kb.service.search import search as svc_search
from l1_kb.service.store import load_store

__all__ = ["app", "run"]

app = FastAPI(title="L1 KB Read-only API", version="0.1.0")

_UNSAFE = re.compile(r"[/\\]|\.\.")


# --- 出口模型 ---
class SectionOut(BaseModel):
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str


class DocumentSummary(BaseModel):
    slug: str
    title: str
    type: str
    updated: str


class DocumentOut(BaseModel):
    slug: str
    type: str
    title: str
    sections: list[SectionOut]


class CategoryOut(BaseModel):
    type: str
    count: int


class IndexPage(BaseModel):
    slug: str
    title: str


class IndexCategory(BaseModel):
    type: str
    pages: list[IndexPage]


class IndexOut(BaseModel):
    updated: str
    categories: list[IndexCategory]


class SearchHitOut(BaseModel):
    doc_id: str
    section_id: str
    title: str
    snippet: str
    score: float
    source: str


class SearchOut(BaseModel):
    query: str
    top_k: int
    hits: list[SearchHitOut]


class HealthOut(BaseModel):
    status: str
    pages: int


def _wiki_root() -> "Path":
    from pathlib import Path
    return Path(config.WIKI_ROOT)


def _updated_of(index_text: str) -> str:
    m = re.search(r"_updated:\s*([^_]+)_", index_text)
    return m.group(1).strip() if m else ""


@app.get("/health", response_model=HealthOut)
def health():
    store = load_store(_wiki_root())
    return HealthOut(status="ok", pages=len(store.pages))


@app.get("/categories", response_model=list[CategoryOut])
def categories():
    store = load_store(_wiki_root())
    out: list[CategoryOut] = []
    for t in PAGE_TYPES:
        n = len(store.by_type.get(t, []))
        if n > 0:
            out.append(CategoryOut(type=t, count=n))
    return out


@app.get("/documents", response_model=list[DocumentSummary])
def documents(
    type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    from l1_kb.ingest.wiki.frontmatter import parse as parse_frontmatter
    store = load_store(_wiki_root())
    pages = store.by_type.get(type, []) if type else store.pages
    start = (page - 1) * page_size
    chunk = pages[start:start + page_size]
    out: list[DocumentSummary] = []
    for p in chunk:
        meta, _ = parse_frontmatter(p.path.read_text(encoding="utf-8"))
        out.append(DocumentSummary(slug=p.slug, title=p.title, type=p.type, updated=meta.updated))
    return out


@app.get("/documents/{slug}", response_model=DocumentOut)
def document(slug: str):
    if _UNSAFE.search(slug):
        raise HTTPException(status_code=404)
    store = load_store(_wiki_root())
    p = store.by_slug.get(slug)
    if p is None:
        raise HTTPException(status_code=404)
    return DocumentOut(
        slug=p.slug, type=p.type, title=p.title,
        sections=[SectionOut(section_id=s.section_id, title=s.title,
                             line_start=s.line_start, line_end=s.line_end, body=s.body)
                  for s in p.sections],
    )


@app.get("/index", response_model=IndexOut)
def index():
    root = _wiki_root()
    idx = root / "index.md"
    if not idx.exists():
        raise HTTPException(status_code=404)
    text = idx.read_text(encoding="utf-8")
    collected = _collect_pages(root)  # dict[type, list[(slug,title)]]
    cats: list[IndexCategory] = []
    for t in PAGE_TYPES:
        items = collected.get(t, [])
        if items:
            cats.append(IndexCategory(type=t, pages=[IndexPage(slug=s, title=t_) for s, t_ in items]))
    return IndexOut(updated=_updated_of(text), categories=cats)


@app.get("/search", response_model=SearchOut)
def search(
    q: str | None = Query(None),
    top_k: int = Query(10, ge=1, le=50),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    q = q.strip()
    store = load_store(_wiki_root())
    hits = svc_search(store, q, top_k=top_k)
    return SearchOut(
        query=q, top_k=top_k,
        hits=[SearchHitOut(doc_id=h.doc_id, section_id=h.section_id, title=h.title,
                           snippet=h.snippet, score=h.score, source=h.source) for h in hits],
    )


def run() -> None:
    """kb-serve 入口。"""
    import uvicorn
    uvicorn.run("l1_kb.service.app:app", host="0.0.0.0", port=8011, reload=False)

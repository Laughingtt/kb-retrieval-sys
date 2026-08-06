"""L1 只读 REST API —— FastAPI 6 个 GET 端点。无写/执行路由（硬约束 2）。

启动：uvicorn kb_retrieval.kb.service.app:app  或  kb-serve
"""

from __future__ import annotations

import re
from pathlib import Path

import kb_retrieval.kb.config as config
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from kb_retrieval.kb.ingest.wiki.index_log import _collect_pages
from kb_retrieval.kb.ingest.wiki.page_type_config import get_registry
from kb_retrieval.kb.service.search import search as svc_search
from kb_retrieval.kb.service.store import load_store

__all__ = ["app", "run"]

app = FastAPI(title="L1 KB Read-only API", version="0.1.0")

_UNSAFE = re.compile(r"[/\\]|\.\.")


def _page_type_order() -> list[str]:
    """类型顺序 = page_types.yaml 的声明顺序。每次调用实时读 registry（测试可切配置）。"""
    return [s.key for s in get_registry().types]


def _label_to_key() -> dict[str, str]:
    """label → key 映射，用于解析 index.md 的 `## label` 段标题回 type。"""
    return {s.label: s.key for s in get_registry().types}


# --- 出口模型 ---
class SectionOut(BaseModel):
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str


class DocumentSummary(BaseModel):
    slug: str
    type: str
    title: str
    section_count: int
    updated: str | None


class PaginatedDocuments(BaseModel):
    items: list[DocumentSummary]
    page: int
    page_size: int
    total: int


class DocumentOut(BaseModel):
    slug: str
    type: str
    title: str
    updated: str | None
    sections: list[SectionOut]


class CategoryOut(BaseModel):
    type: str
    count: int


class IndexEntry(BaseModel):
    type: str
    title: str
    slug: str


class IndexOut(BaseModel):
    entries: list[IndexEntry]


class SearchHitOut(BaseModel):
    doc_id: str
    section_id: str
    title: str
    snippet: str
    score: float
    source: str


class SearchOut(BaseModel):
    query: str
    total: int
    hits: list[SearchHitOut]


class HealthOut(BaseModel):
    status: str
    wiki_root: str
    page_count: int
    last_updated: str | None


def _wiki_root() -> Path:
    return Path(config.WIKI_ROOT)


def _page_updated(p) -> str | None:
    """Re-parse frontmatter to get updated; None if empty."""
    from kb_retrieval.kb.ingest.wiki.frontmatter import parse as parse_frontmatter
    meta, _ = parse_frontmatter(p.path.read_text(encoding="utf-8"))
    return meta.updated or None


def _parse_index_md(idx_path: Path) -> list[IndexEntry]:
    """Parse wiki/index.md → flat list of IndexEntry. Returns [] on failure.

    段标题用类型 label（人类可读）；解析时经 label→key 映射回 type。
    向后兼容：映射未命中时回退用 header 本身当 type（兼容旧 index.md 的 raw key 标题）。
    """
    try:
        text = idx_path.read_text(encoding="utf-8")
    except OSError:
        return []
    label_to_key = _label_to_key()
    entries: list[IndexEntry] = []
    cur_type: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            header = s[3:].strip()
            cur_type = label_to_key.get(header, header)
            continue
        if s.startswith("- [[") and "]]" in s:
            inner = s[4:s.index("]]")]
            if "|" in inner:
                slug, title = inner.split("|", 1)
            else:
                slug, title = inner, inner
            if cur_type:
                entries.append(IndexEntry(type=cur_type, title=title.strip(), slug=slug.strip()))
    return entries


def _fallback_entries(root: Path) -> list[IndexEntry]:
    """Derive entries from _collect_pages(by_type). Title-sorted per group."""
    collected = _collect_pages(root)
    out: list[IndexEntry] = []
    for t in _page_type_order():
        for slug, title in collected.get(t, []):
            out.append(IndexEntry(type=t, title=title, slug=slug))
    return out


@app.get("/health", response_model=HealthOut)
def health():
    store = load_store(_wiki_root())
    updated_vals = [_page_updated(p) for p in store.pages]
    last_updated = max((u for u in updated_vals if u), default=None)
    return HealthOut(
        status="ok",
        wiki_root=str(config.WIKI_ROOT),
        page_count=len(store.pages),
        last_updated=last_updated,
    )


@app.get("/categories", response_model=list[CategoryOut])
def categories():
    store = load_store(_wiki_root())
    return [CategoryOut(type=t, count=len(store.by_type.get(t, []))) for t in _page_type_order()]


@app.get("/documents", response_model=PaginatedDocuments)
def documents(
    type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    valid_types = {s.key for s in get_registry().types}
    if type and type not in valid_types:
        raise HTTPException(status_code=422, detail=f"unknown page type: {type}")
    store = load_store(_wiki_root())
    if type:
        pages = list(store.by_type.get(type, []))
    else:
        pages = list(store.pages)
    # sort: 按 type 升序（canonical order，与 index_log.rebuild_index 一致）、组内按 title 升序
    order = _page_type_order()
    type_rank = {t: i for i, t in enumerate(order)}
    pages.sort(key=lambda p: (type_rank.get(p.type, len(order)), p.title))
    total = len(pages)
    start = (page - 1) * page_size
    chunk = pages[start:start + page_size]
    items = [
        DocumentSummary(
            slug=p.slug, type=p.type, title=p.title,
            section_count=len(p.sections), updated=_page_updated(p),
        )
        for p in chunk
    ]
    return PaginatedDocuments(items=items, page=page, page_size=page_size, total=total)


@app.get("/documents/{slug}", response_model=DocumentOut)
def document(slug: str):
    if _UNSAFE.search(slug):
        raise HTTPException(status_code=404, detail=f"document not found: {slug}")
    store = load_store(_wiki_root())
    p = store.by_slug.get(slug)
    if p is None:
        raise HTTPException(status_code=404, detail=f"document not found: {slug}")
    return DocumentOut(
        slug=p.slug, type=p.type, title=p.title, updated=_page_updated(p),
        sections=[SectionOut(section_id=s.section_id, title=s.title,
                             line_start=s.line_start, line_end=s.line_end, body=s.body)
                  for s in p.sections],
    )


@app.get("/index", response_model=IndexOut)
def index():
    root = _wiki_root()
    idx = root / "index.md"
    entries = _parse_index_md(idx) if idx.exists() else []
    if not entries:
        entries = _fallback_entries(root)
    return IndexOut(entries=entries)


@app.get("/search", response_model=SearchOut)
def search(
    q: str | None = Query(None),
    top_k: int = Query(10, ge=1, le=50),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    q = q.strip()
    store = load_store(_wiki_root())
    hits = svc_search(store, q, top_k=top_k)
    return SearchOut(
        query=q, total=len(hits),
        hits=[SearchHitOut(doc_id=h.doc_id, section_id=h.section_id, title=h.title,
                           snippet=h.snippet, score=h.score, source=h.source) for h in hits],
    )


def run() -> None:
    """kb-serve 入口。"""
    import uvicorn
    uvicorn.run("kb_retrieval.kb.service.app:app", host="0.0.0.0", port=8011, reload=False)

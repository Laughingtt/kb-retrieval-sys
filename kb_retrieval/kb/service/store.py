"""L1 只读 service —— wiki → WikiStore（纯函数，与 HTTP 解耦）。

下沉自 cli/kb.py:_wiki_entries。供 service.search 与 FastAPI 路由复用（DRY）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kb_retrieval.kb.ingest.section_splitter import split as split_sections
from kb_retrieval.kb.ingest.wiki.frontmatter import parse as parse_frontmatter
from kb_retrieval.kb.ingest.wiki.page_types import PAGE_TYPES
from kb_retrieval.kb.retrieval.snippet import make_snippet

__all__ = ["SectionEntry", "PageEntry", "WikiStore", "load_store"]

_EXCLUDED_STEMS = {"index", "log", "overview"}
_MAX_BODY_CHARS = 2000
_TRUNC_MARK = "…[截断]"


@dataclass
class SectionEntry:
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str


@dataclass
class PageEntry:
    slug: str
    type: str
    title: str
    path: Path
    sections: list[SectionEntry]
    raw: str


@dataclass
class WikiStore:
    pages: list[PageEntry]
    by_slug: dict[str, PageEntry] = field(default_factory=dict)
    by_type: dict[str, list[PageEntry]] = field(default_factory=dict)


def _truncate(text: str, max_chars: int = _MAX_BODY_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNC_MARK


def load_store(wiki_root: Path) -> WikiStore:
    """扫 wiki_root/**/*.md → WikiStore。跳过 index/log/overview。空目录返回空 store。"""
    wiki_root = Path(wiki_root)
    pages: list[PageEntry] = []
    if not wiki_root.exists():
        return WikiStore(pages=[])
    for md_path in sorted(wiki_root.rglob("*.md")):
        if md_path.stem in _EXCLUDED_STEMS:
            continue
        text = md_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        slug = md_path.stem
        ptype = meta.type or ""
        title = meta.title or slug
        secs: list[SectionEntry] = []
        for s in split_sections(body):
            # make_snippet 切行范围（不在此处截断，留给 _truncate 带标记截断）
            seg = make_snippet(body, s.line_start, s.line_end, max_chars=len(body) + 1)
            secs.append(SectionEntry(
                section_id=s.section_id,
                title=s.title,
                line_start=s.line_start,
                line_end=s.line_end,
                body=_truncate(seg, _MAX_BODY_CHARS),
            ))
        pages.append(PageEntry(
            slug=slug, type=ptype, title=title,
            path=md_path, sections=secs, raw=body,
        ))
    pages.sort(key=lambda p: p.slug)
    by_slug = {p.slug: p for p in pages}
    by_type: dict[str, list[PageEntry]] = {t: [] for t in PAGE_TYPES}
    for p in pages:
        by_type.setdefault(p.type, []).append(p)
    return WikiStore(pages=pages, by_slug=by_slug, by_type=by_type)

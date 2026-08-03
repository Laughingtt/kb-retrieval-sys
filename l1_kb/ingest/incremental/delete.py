# l1_kb/ingest/incremental/delete.py
"""精准反向清理 —— M3 设计 §二。

slug → md 文件（glob）→ source_identity → ingest-cache[identity].paths[] → 删 wiki 页
→ 删 md → 删 cache 条目 → 删 hash 条目 → rebuild_index。
理解原理后用 Python 重新实现，非复制 llm_wiki。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..wiki.index_log import rebuild_index
from ..wiki.ingest_cache import _load as _load_cache, _save as _save_cache  # M2 同包私有名，耦合点
from .hash_store import load_hash, remove_hash

__all__ = ["PurgeResult", "find_md_for_slug", "purge_source"]


@dataclass
class PurgeResult:
    slug: str
    deleted_pages: list[str] = field(default_factory=list)
    deleted_md: bool = False


def find_md_for_slug(md_root: Path, slug: str) -> Path | None:
    """glob **/{slug}__*.md，命中第一个返回绝对路径。"""
    if not md_root.exists():
        return None
    for p in sorted(md_root.rglob(f"{slug}__*.md")):
        return p
    return None


def _glob_source_pages(wiki_root: Path, slug: str) -> list[Path]:
    """cache 缺失时兜底：删 sources/{slug}__*.md。"""
    pages = []
    src_dir = wiki_root / "sources"
    if src_dir.exists():
        pages.extend(sorted(src_dir.glob(f"{slug}__*.md")))
    return pages


def purge_source(*, slug: str, md_root: Path, wiki_root: Path, cache_path: Path,
                hash_path: Path, today: str) -> PurgeResult:
    """精准反向清理一个源。"""
    res = PurgeResult(slug=slug)
    md_path = find_md_for_slug(md_root, slug)

    # 取权威页列表：cache[identity].paths[]，无则 glob 兜底
    page_paths: list[Path] = []
    if md_path is not None:
        identity = str(md_path)
        cache = _load_cache(cache_path)
        entry = cache.get(identity)
        if entry and entry.get("paths"):
            page_paths = [Path(p) for p in entry["paths"]]
            # 删 cache 条目
            if identity in cache:
                del cache[identity]
                _save_cache(cache_path, cache)
        else:
            page_paths = _glob_source_pages(wiki_root, slug)
    else:
        page_paths = _glob_source_pages(wiki_root, slug)

    # 删 wiki 页
    for p in page_paths:
        if p.exists():
            p.unlink()
            res.deleted_pages.append(str(p))

    # 删 md
    if md_path is not None and md_path.exists():
        md_path.unlink()
        res.deleted_md = True

    # 删 hash 条目
    remove_hash(hash_path, slug)

    # 重建 index（无幽灵）
    rebuild_index(wiki_root, today)
    return res

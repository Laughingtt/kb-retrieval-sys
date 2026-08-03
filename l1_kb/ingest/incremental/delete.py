# l1_kb/ingest/incremental/delete.py
"""精准反向清理 —— M3 设计 §二。

slug → md 文件（glob）→ source_identity → ingest-cache[identity].paths[] → 删 wiki 页
→ 删 md → 删 cache 条目 → 删 hash 条目 → rebuild_index。
理解原理后用 Python 重新实现，非复制 llm_wiki。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..wiki.index_log import rebuild_index
from ..wiki.ingest_cache import _load as _load_cache, _save as _save_cache  # M2 同包私有名，耦合点
from .hash_store import load_hash, remove_hash

__all__ = ["PurgeResult", "find_md_for_slug", "purge_source"]

_HASH8_TAIL_RE = re.compile(r"__[0-9a-f]{8}$")


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


def _slug_of_md_identity(identity: str) -> str:
    """从 cache key（md 绝对路径）反推 slug：取文件名去 __{8hex} 后缀。

    identity 形如 /abs/.../data_table/data_table_order_detail__a3f9c1e2.md
    → stem = data_table_order_detail__a3f9c1e2 → 去 __{8hex} → data_table_order_detail。
    无 __{8hex} 后缀原样返回 stem（best-effort）。
    """
    stem = Path(identity).stem
    return _HASH8_TAIL_RE.sub("", stem)


def purge_source(*, slug: str, md_root: Path, wiki_root: Path, cache_path: Path,
                hash_path: Path, today: str, purge_md: bool = True) -> PurgeResult:
    """精准反向清理一个源。

    页面定位策略（修正 M3：identity=str(md_path) 后 fallback 页名不再形如
    {slug}__*.md，故不能仅靠 slug glob 兜底）：
    1. 遍历 cache 所有 key（md 绝对路径），反推 slug，凡 == 目标 slug 者，
       收集其 paths[]（这些是待删 wiki 页）并标记该 key 待删。
       —— 这能命中“旧 md 已删但 cache 条目仍在”的 modify 场景。
    2. 若 find_md_for_slug 命中当前 md 且其 cache 条目存在，补齐其 paths[]
       （覆盖常规 delete：md 仍在，cache key = 当前 md 路径）。
    3. 仍空 → glob sources/{slug}__*.md 兜底（best-effort，历史路径形态）。
    """
    res = PurgeResult(slug=slug)
    md_path = find_md_for_slug(md_root, slug)

    cache = _load_cache(cache_path)
    page_paths: list[Path] = []
    keys_to_delete: list[str] = []

    # 1. 遍历 cache：反推 slug 匹配 → 收集 paths + 标记删除
    for key, entry in cache.items():
        if _slug_of_md_identity(key) != slug:
            continue
        if entry and entry.get("paths"):
            for p in entry["paths"]:
                pp = Path(p)
                if pp not in page_paths:
                    page_paths.append(pp)
        keys_to_delete.append(key)

    # 2. 当前 md 的 cache 条目补齐（常规 delete 场景：md 仍在）
    if md_path is not None:
        identity = str(md_path)
        entry = cache.get(identity)
        if entry and entry.get("paths"):
            for p in entry["paths"]:
                pp = Path(p)
                if pp not in page_paths:
                    page_paths.append(pp)
            if identity not in keys_to_delete:
                keys_to_delete.append(identity)

    # 3. 仍空 → glob 兜底
    if not page_paths:
        page_paths = _glob_source_pages(wiki_root, slug)

    # 删 wiki 页
    for p in page_paths:
        if p.exists():
            p.unlink()
            res.deleted_pages.append(str(p))

    # 删 cache 条目（一次性写回）
    if keys_to_delete:
        for k in keys_to_delete:
            cache.pop(k, None)
        _save_cache(cache_path, cache)

    # 删 md（仅 purge_md=True 时；modify 路径需保留新 md 供 _ingest_one）
    if purge_md and md_path is not None and md_path.exists():
        md_path.unlink()
        res.deleted_md = True

    # 删 hash 条目
    remove_hash(hash_path, slug)

    # 重建 index（无幽灵）
    rebuild_index(wiki_root, today)
    return res

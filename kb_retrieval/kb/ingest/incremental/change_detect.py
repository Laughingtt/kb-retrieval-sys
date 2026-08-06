# kb_retrieval/kb/ingest/incremental/change_detect.py
"""扫 raw/ 对比 hash.json → 四态 —— M3 设计 §三。

add=无记录且存在；modify=有记录但 hash 变；skip=有记录 hash 不变；
delete=hash.json 有记录但 raw 文件已不在。理解原理后用 Python 重新实现。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..cleaners.dispatcher import SUPPORTED_EXTS
from ..doc_id import make_doc_id, slugify_path
from .hash_store import load_hash

__all__ = ["ChangeItem", "DeleteItem", "ChangeSet", "detect_changes", "slug_of", "hash_raw"]

_HASH8_RE = re.compile(r"__[0-9a-f]{8}$")


def slug_of(doc_id: str) -> str:
    """doc_id 去掉 __{8hex} 后缀 → slug。无后缀原样返回。"""
    return _HASH8_RE.sub("", doc_id)


def hash_raw(raw_path: Path) -> str:
    return "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()


@dataclass
class ChangeItem:
    slug: str
    raw_path: Path          # 绝对路径
    raw_rel: str            # POSIX 相对 raw_root
    doc_id: str
    hash: str               # "sha256:..."


@dataclass
class DeleteItem:
    slug: str
    raw_rel: str            # 来自 hash.json 记录的 path


@dataclass
class ChangeSet:
    add: list[ChangeItem] = field(default_factory=list)
    modify: list[ChangeItem] = field(default_factory=list)
    delete: list[DeleteItem] = field(default_factory=list)
    skip: list[ChangeItem] = field(default_factory=list)


def detect_changes(raw_root: Path, hash_path: Path) -> ChangeSet:
    """扫 raw/ 下 SUPPORTED_EXTS 文件，对比 hash.json，产出四集。"""
    raw_root = raw_root.resolve()
    known = load_hash(hash_path)  # {slug: {hash, path, ingested_at}}
    seen_slugs: set[str] = set()
    cs = ChangeSet()

    if raw_root.exists():
        for f in sorted(raw_root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXTS:
                continue
            rel = f.relative_to(raw_root)
            rel_posix = str(rel).replace("\\", "/")
            doc_id = make_doc_id(raw_root, f)
            slug = slug_of(doc_id)
            seen_slugs.add(slug)
            h = hash_raw(f)
            item = ChangeItem(slug=slug, raw_path=f, raw_rel=rel_posix,
                              doc_id=doc_id, hash=h)
            rec = known.get(slug)
            if rec is None:
                cs.add.append(item)
            elif rec.get("hash") != h:
                cs.modify.append(item)
            else:
                cs.skip.append(item)

    # delete：hash.json 有但 raw 里没扫到
    for slug, rec in known.items():
        if slug not in seen_slugs:
            cs.delete.append(DeleteItem(slug=slug, raw_rel=rec.get("path", "")))
    return cs

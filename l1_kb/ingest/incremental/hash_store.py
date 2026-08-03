# l1_kb/ingest/incremental/hash_store.py
"""hash.json 读写 —— M3 设计 §二。

raw 层变更检测权威存储。键=slug（doc_id 去掉 __hash8 后缀，稳定身份）；
值={hash, path, ingested_at}。理解原理后用 Python 重新实现，非复制 llm_wiki。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = ["load_hash", "save_hash", "upsert_hash", "remove_hash"]


def load_hash(hash_path: Path) -> dict[str, dict]:
    """不存在/损坏 → {}。"""
    if not hash_path.exists():
        return {}
    try:
        return json.loads(hash_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_hash(hash_path: Path, data: dict) -> None:
    """原子写（tmp + os.replace）。"""
    hash_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = hash_path.with_suffix(hash_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, hash_path)


def upsert_hash(hash_path: Path, slug: str, *, hash: str, path: str, ingested_at: str) -> None:
    """load → 改单键 → save。"""
    data = load_hash(hash_path)
    data[slug] = {"hash": hash, "path": path, "ingested_at": ingested_at}
    save_hash(hash_path, data)


def remove_hash(hash_path: Path, slug: str) -> None:
    """删键；不存在不报错。"""
    data = load_hash(hash_path)
    if slug in data:
        del data[slug]
        save_hash(hash_path, data)

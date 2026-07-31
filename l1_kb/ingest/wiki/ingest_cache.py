"""ingest-cache —— M2 设计 §3.8。

吸收 llm_wiki ingest-cache.ts 原理（Python 重实现）：sha256(source content) 命中
仅当 hash 匹配 **且** 之前写入的所有 wiki 页仍存在于磁盘（防幽灵条目——
某页被删则视为未摄入，重跑两步 LLM）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = ["content_hash", "check_cache", "save_cache"]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(cache_path: Path, data: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    import os

    os.replace(tmp, cache_path)


def check_cache(cache_path: Path, source_identity: str, content_hash_value: str) -> bool:
    """命中仅当 hash 匹配且所有 written_paths 仍存在。"""
    data = _load(cache_path)
    entry = data.get(source_identity)
    if not entry:
        return False
    if entry.get("hash") != content_hash_value:
        return False
    # 落盘校验防幽灵
    for p in entry.get("paths", []):
        if not Path(p).exists():
            return False
    return True


def save_cache(cache_path: Path, source_identity: str, content_hash_value: str, written_paths: list[str]) -> None:
    data = _load(cache_path)
    data[source_identity] = {"hash": content_hash_value, "paths": list(written_paths)}
    _save(cache_path, data)

# kb_retrieval/kb/ingest/incremental/ingest_log.py
"""ingest_log.jsonl append-only 时序日志 —— M3 设计 §二。

对齐 PRD §9.7 行格式。ts 用调用方传入的日期（config.today()）。理解原理后用 Python 重新实现。
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["append_ingest", "append_delete", "append_lint", "append_rebuild", "read_log"]


def _append(log_path: Path, obj: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def append_ingest(log_path: Path, *, today: str, doc_id: str, action: str, source: str) -> None:
    _append(log_path, {"ts": today, "type": "ingest", "doc_id": doc_id,
                        "action": action, "source": source})


def append_delete(log_path: Path, *, today: str, doc_id: str, source: str) -> None:
    _append(log_path, {"ts": today, "type": "delete", "doc_id": doc_id, "source": source})


def append_lint(log_path: Path, *, today: str, issues: int, errors: int, warnings: int, info: int) -> None:
    _append(log_path, {"ts": today, "type": "lint", "issues": issues,
                        "errors": errors, "warnings": warnings, "info": info})


def append_rebuild(log_path: Path, *, today: str) -> None:
    _append(log_path, {"ts": today, "type": "rebuild"})


def read_log(log_path: Path) -> list[dict]:
    """每行一 JSON，坏行跳过；不存在→[]。"""
    if not log_path.exists():
        return []
    out = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out

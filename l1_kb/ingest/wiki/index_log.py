"""确定性 index.md 重建 / log.md 追加 —— M2 设计 §4。

吸收 llm_wiki updateWikiIndexDeterministically + buildDeterministicIngestLog
原理（Python 重实现，不用 LLM）。index.md 按 frontmatter type 分组、组内按
title 排序、原子 temp+rename 写入。log.md 追加 `## [YYYY-MM-DD] ingest | {identity}`。
"""

from __future__ import annotations

import os
from pathlib import Path

from .frontmatter import parse
from .page_types import PAGE_TYPES

__all__ = ["rebuild_index", "append_log"]

_EXCLUDED_STEMS = {"index", "log", "overview"}


def _collect_pages(wiki_root: Path) -> dict[str, list[tuple[str, str]]]:
    """遍历 wiki/*.md（排除 index/log/overview 茎），按 type 分组 → {type: [(slug, title)]}。"""
    groups: dict[str, list[tuple[str, str]]] = {t: [] for t in PAGE_TYPES}
    if not wiki_root.exists():
        return groups
    for p in sorted(wiki_root.rglob("*.md")):
        stem = p.stem
        if stem in _EXCLUDED_STEMS:
            continue
        text = p.read_text(encoding="utf-8")
        meta, _ = parse(text)
        if meta.type not in PAGE_TYPES:
            continue
        groups[meta.type].append((stem, meta.title or stem))
    for t in groups:
        groups[t].sort(key=lambda x: x[1])  # 按 title 排序
    return groups


def rebuild_index(wiki_root: Path, today: str) -> None:
    """重建 wiki/index.md（确定性，原子写）。"""
    groups = _collect_pages(wiki_root)
    lines = ["# Wiki Index", f"_" + f"updated: {today}" + "_", ""]
    any_pages = False
    for t in ("source", "entity", "concept", "process"):
        pages = groups.get(t, [])
        if not pages:
            continue
        any_pages = True
        lines.append(f"## {t}")
        for slug, title in pages:
            lines.append(f"- [[{slug}|{title}]]")
        lines.append("")
    if not any_pages:
        lines.append("_(暂无页面)_")
    content = "\n".join(lines).rstrip() + "\n"
    wiki_root.mkdir(parents=True, exist_ok=True)
    tmp = wiki_root / ".index.md.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, wiki_root / "index.md")


def append_log(wiki_root: Path, source_identity: str, today: str) -> None:
    """追加 log.md 一行。首行 # Wiki Log。"""
    wiki_root.mkdir(parents=True, exist_ok=True)
    log_path = wiki_root / "log.md"
    line = f"## [{today}] ingest | {source_identity}"
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        if not existing.startswith("# Wiki Log"):
            existing = "# Wiki Log\n\n" + existing
        content = existing.rstrip() + "\n" + line + "\n"
    else:
        content = f"# Wiki Log\n\n{line}\n"
    log_path.write_text(content, encoding="utf-8")

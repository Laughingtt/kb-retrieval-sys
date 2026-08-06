# kb_retrieval/kb/ingest/lint/checker.py
"""L1-L5 确定性自检 —— M3 设计 §四。

纯脚本不调 LLM。复用 M2 frontmatter.parse 读每页。理解原理后用 Python 重新实现。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..wiki.frontmatter import parse as parse_fm
from ..wiki.page_types import PAGE_TYPES, TYPE_TO_DIR
from ..wiki.page_type_config import get_registry
from ..incremental.hash_store import load_hash
from ..incremental.ingest_log import read_log

__all__ = ["Issue", "LintReport", "JACCARD_THRESHOLD", "run_lint"]

JACCARD_THRESHOLD = 0.5
_EXCLUDED_STEMS = {"index", "log", "overview"}
_INDEX_LINK_RE = re.compile(r"^- \[\[([^|\]]+)\|[^\]]*\]\]", re.MULTILINE)


@dataclass
class Issue:
    code: str
    level: str          # error | warn | info
    msg: str
    page: str = ""
    type: str = ""


@dataclass
class LintReport:
    issues: list[Issue] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    info: int = 0
    ts: str = ""


def _iter_pages(wiki_root: Path):
    """yield (path, stem, frontmatter, text) for valid-type wiki pages."""
    if not wiki_root.exists():
        return
    for p in sorted(wiki_root.rglob("*.md")):
        if p.stem in _EXCLUDED_STEMS:
            continue
        text = p.read_text(encoding="utf-8")
        fm, _ = parse_fm(text)
        if fm.type in PAGE_TYPES:
            yield p, p.stem, fm, text


def _check_l1(wiki_root: Path, hash_path: Path, lp: Path, cache_path: Path, issues: list[Issue]) -> None:
    idx = wiki_root / "index.md"
    if not idx.exists() or not idx.read_text(encoding="utf-8").startswith("# Wiki Index"):
        issues.append(Issue("L1_FORMAT", "error", "index.md 缺失或首行非 # Wiki Index"))
    logmd = wiki_root / "log.md"
    if not logmd.exists() or not logmd.read_text(encoding="utf-8").startswith("# Wiki Log"):
        issues.append(Issue("L1_FORMAT", "error", "log.md 缺失或首行非 # Wiki Log"))
    # ingest_log.jsonl 每行合法 JSON 含 ts/type
    if lp.exists():
        for ln in lp.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
                if "ts" not in obj or "type" not in obj:
                    issues.append(Issue("L1_FORMAT", "error", f"ingest_log 行缺 ts/type: {ln[:60]}"))
                    break
            except json.JSONDecodeError:
                issues.append(Issue("L1_FORMAT", "error", f"ingest_log 行非法 JSON: {ln[:60]}"))
                break
    # hash.json / cache.json 合法 JSON
    if hash_path.exists():
        try:
            json.loads(hash_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            issues.append(Issue("L1_FORMAT", "error", "hash.json 非法 JSON"))
    if cache_path.exists():
        try:
            json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            issues.append(Issue("L1_FORMAT", "error", "ingest-cache.json 非法 JSON"))


def _disk_slugs(wiki_root: Path) -> set[str]:
    return {stem for _, stem, _, _ in _iter_pages(wiki_root)}


def _index_slugs(wiki_root: Path) -> set[str]:
    idx = wiki_root / "index.md"
    if not idx.exists():
        return set()
    return set(_INDEX_LINK_RE.findall(idx.read_text(encoding="utf-8")))


def _check_l2(wiki_root: Path, issues: list[Issue]) -> None:
    disk = _disk_slugs(wiki_root)
    index = _index_slugs(wiki_root)
    for slug in sorted(index - disk):
        issues.append(Issue("L2_GHOST", "error", "index.md 列出但磁盘无此页", page=slug))
    for slug in sorted(disk - index):
        issues.append(Issue("L2_MISSING", "warn", "磁盘有页但 index 未列", page=slug))


def _check_l3(wiki_root: Path, issues: list[Issue]) -> None:
    pointed: set[str] = set()
    pages = list(_iter_pages(wiki_root))
    for _, _, fm, _ in pages:
        pointed.update(fm.related)
    registry = get_registry()
    for _, stem, fm, _ in pages:
        spec = registry.by_key.get(fm.type)
        if spec is not None and spec.orphan_exempt:
            continue  # 配置豁免（source 摘要页不报孤儿）
        if stem not in pointed:
            issues.append(Issue("L3_ORPHAN", "warn", "无 related 指向", page=stem, type=fm.type))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _check_l4(wiki_root: Path, issues: list[Issue]) -> None:
    registry = get_registry()
    xref_types = {s.key for s in registry.types if s.xref_check}
    pages = [(stem, fm) for _, stem, fm, _ in _iter_pages(wiki_root)
             if fm.type in xref_types]
    for i, (s1, f1) in enumerate(pages):
        for s2, f2 in pages[i + 1:]:
            if _jaccard(set(f1.tags), set(f2.tags)) >= JACCARD_THRESHOLD:
                if s2 not in f1.related and s1 not in f2.related:
                    issues.append(Issue("L4_XREF", "warn",
                                    f"tags 重叠但无交叉引用: {s1} ↔ {s2}", page=s1))


def _check_l5(wiki_root: Path, issues: list[Issue]) -> None:
    for t, d in TYPE_TO_DIR.items():
        dpath = wiki_root / d
        count = 0
        if dpath.exists():
            count = sum(1 for p in dpath.glob("*.md") if p.stem not in _EXCLUDED_STEMS)
        if count == 0:
            issues.append(Issue("L5_GAP", "info", f"{t} 类型 0 页", type=t))


def run_lint(*, wiki_root: Path, hash_path: Path, ingest_log_path: Path,
             cache_path: Path, md_root: Path, today: str) -> LintReport:
    rep = LintReport(ts=today)
    _check_l1(wiki_root, hash_path, ingest_log_path, cache_path, rep.issues)
    _check_l2(wiki_root, rep.issues)
    _check_l3(wiki_root, rep.issues)
    _check_l4(wiki_root, rep.issues)
    _check_l5(wiki_root, rep.issues)
    rep.errors = sum(1 for i in rep.issues if i.level == "error")
    rep.warnings = sum(1 for i in rep.issues if i.level == "warn")
    rep.info = sum(1 for i in rep.issues if i.level == "info")
    return rep

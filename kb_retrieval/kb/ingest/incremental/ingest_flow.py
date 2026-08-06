# kb_retrieval/kb/ingest/incremental/ingest_flow.py
"""三态编排 —— M3 设计 §三。

扫 raw → 四态 → add/modify/delete 分发。单文档事务：wiki/cache 写成功后才
upsert_hash + append_log（hash.json 最后落盘=提交）。理解原理后用 Python 重新实现。
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..clean import clean_one
from ..cleaners.dispatcher import SUPPORTED_EXTS
from ..wiki.ingest import ingest_source, read_index_md
from .change_detect import ChangeItem, ChangeSet, detect_changes
from .delete import find_md_for_slug, purge_source
from .hash_store import upsert_hash
from .ingest_log import append_delete, append_ingest, append_rebuild

__all__ = ["FlowSummary", "run_incremental", "rebuild_all"]


def _warn(msg: str) -> None:
    print(f"[warn] ingest_flow: {msg}", file=sys.stderr)


@dataclass
class FlowSummary:
    added: int = 0
    modified: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    details: list[str] = field(default_factory=list)


def _ingest_one(item: ChangeItem, *, action: str, md_root: Path, wiki_root: Path,
                 cache_path: Path, hash_path: Path, log_path: Path, client, today: str) -> bool:
    """add/modify 共用：glob 找 md → ingest_source → 成功后 upsert_hash + log。返回是否成功。"""
    md_path = find_md_for_slug(md_root, item.slug)
    if md_path is None:
        _warn(f"{item.slug}: 未找到 md，请先 kb clean {item.raw_rel}")
        append_ingest(log_path, today=today, doc_id=item.doc_id, action="skipped_no_md",
                       source=item.raw_rel)
        return None  # 信号：warn，非失败
    identity = str(md_path)
    index_md = read_index_md(wiki_root)
    res = ingest_source(md_path, identity, wiki_root=wiki_root, cache_path=cache_path,
                        client=client, today=today, index_md=index_md)
    # 事务提交：hash 最后落盘
    upsert_hash(hash_path, item.slug, hash=item.hash, path=item.raw_rel, ingested_at=today)
    append_ingest(log_path, today=today, doc_id=item.doc_id, action=action, source=item.raw_rel)
    return True


def run_incremental(*, raw_root: Path, md_root: Path, wiki_root: Path, cache_path: Path,
                    hash_path: Path, log_path: Path, client, today: str) -> FlowSummary:
    cs = detect_changes(raw_root, hash_path)
    summ = FlowSummary()

    # add + modify（modify 先 purge 旧页=delete-then-add）
    for item in cs.add:
        summ.total += 1
        try:
            r = _ingest_one(item, action="add", md_root=md_root, wiki_root=wiki_root,
                            cache_path=cache_path, hash_path=hash_path, log_path=log_path,
                            client=client, today=today)
            if r is None:
                summ.details.append(f"[WARN] {item.slug}: 无 md，跳过")
            elif r:
                summ.added += 1
                summ.details.append(f"[ADD] {item.slug}")
        except Exception as e:  # noqa: BLE001
            summ.failed += 1
            summ.details.append(f"[ERR] {item.slug}: {e}")

    for item in cs.modify:
        summ.total += 1
        try:
            # modify = delete-then-add：purge 旧 wiki 页 + 旧 cache 条目，
            # 但 purge_md=False 保留新 md 供 _ingest_one 摄入（旧 md 已被 clean 删）。
            purge_source(slug=item.slug, md_root=md_root, wiki_root=wiki_root,
                         cache_path=cache_path, hash_path=hash_path, today=today,
                         purge_md=False)
            r = _ingest_one(item, action="modify", md_root=md_root, wiki_root=wiki_root,
                            cache_path=cache_path, hash_path=hash_path, log_path=log_path,
                            client=client, today=today)
            if r is None:
                summ.details.append(f"[WARN] {item.slug}: 无 md，跳过")
            elif r:
                summ.modified += 1
                summ.details.append(f"[MODIFY] {item.slug}")
        except Exception as e:  # noqa: BLE001
            summ.failed += 1
            summ.details.append(f"[ERR] {item.slug}: {e}")

    # skip
    for item in cs.skip:
        summ.total += 1
        summ.skipped += 1
        summ.details.append(f"[SKIP] {item.slug}")

    # delete（扫完统一处理）
    for d in cs.delete:
        summ.total += 1
        try:
            purge_source(slug=d.slug, md_root=md_root, wiki_root=wiki_root,
                         cache_path=cache_path, hash_path=hash_path, today=today)
            append_delete(log_path, today=today, doc_id=d.slug, source=d.raw_rel)
            summ.deleted += 1
            summ.details.append(f"[DELETE] {d.slug}")
        except Exception as e:  # noqa: BLE001
            summ.failed += 1
            summ.details.append(f"[ERR] {d.slug}: {e}")

    return summ


def _clear_generated(md_root, wiki_root, cache_path, hash_path, log_path):
    if md_root.exists(): shutil.rmtree(md_root)
    md_root.mkdir(parents=True, exist_ok=True)
    if wiki_root.exists(): shutil.rmtree(wiki_root)
    wiki_root.mkdir(parents=True, exist_ok=True)
    for p in (cache_path, hash_path, log_path):
        if p.exists(): p.unlink()


def rebuild_all(*, raw_root: Path, md_root: Path, wiki_root: Path, cache_path: Path,
                hash_path: Path, log_path: Path, client, today: str) -> FlowSummary:
    """清生成物从 raw 全量重建。幂等（raw 是真相源）。"""
    _clear_generated(md_root, wiki_root, cache_path, hash_path, log_path)
    # 1) 全量 clean
    raw_files = sorted(p for p in raw_root.rglob("*")
                       if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)
    details: list[str] = []
    ok = 0; failed = 0
    for f in raw_files:
        try:
            clean_one(raw_root, f, md_root, dry_run=False)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed += 1; details.append(f"[ERR] clean {f.name}: {e}")
    # 2) 全量 ingest（cache 已清→全重跑）
    summ = run_incremental(raw_root=raw_root, md_root=md_root, wiki_root=wiki_root,
                           cache_path=cache_path, hash_path=hash_path, log_path=log_path,
                           client=client, today=today)
    # 3) 全量 hash.json 已在 run_incremental 内按需 upsert；这里补一行 rebuild 标记
    append_rebuild(log_path, today=today)
    details.append(f"[REBUILD] clean {ok} / ingest {summ.added} / failed {failed + summ.failed}")
    return FlowSummary(added=summ.added, modified=0, deleted=0, skipped=summ.skipped,
                       failed=failed + summ.failed, total=summ.total + failed,
                       details=details + summ.details)

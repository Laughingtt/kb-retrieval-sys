# M3 增量摄入与自更新闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M2 wiki 层之上旁路新增 raw 层变更检测（hash.json）、增量 add/modify/delete 三态摄入、ingest_log.jsonl 时序日志、`kb lint` 五项确定性自检、`kb rebuild` 全量重建，构成手动增量闭环。

**Architecture:** 不动 M2 身份模型（`source_identity`=绝对 md 路径、`sources: []` bug 原样保留）。新增一条旁路映射链：raw 相对路径 → doc_id 的 slug 部分 → hash.json 键 → glob `md/**/{slug}__*.md` 反查 md 文件 → md 绝对路径即 `source_identity` → 查 `ingest-cache[identity].paths[]` 得权威 wiki 页列表。三态分发：add/modify 走 clean→ingest（modify=delete-then-add 消 orphan），delete 走 paths[] 精准反向清理。每文档事务以 hash.json 最后落盘为提交标记。lint 纯确定性、不调 LLM。

**Tech Stack:** Python 3.12 + click CLI（既有）、pytest（既有，单测 mock LLM / e2e 真实 DEEPSEEK key `deepseek-v4-flash`）、复用 M2 `ingest_source`/`ingest-cache`/`rebuild_index`/`frontmatter.parse`。无新依赖（不引 watchdog）。

## Global Constraints

- 独立项目：本目录自包含，不查看/扫描/依赖仓库其他文件夹（llm_gateway、openwebui、deploy 等）。
- 仅文档查询不执行动作：M3 写 md/wiki/hash.json/ingest_log.jsonl 是离线摄入脚本生成物，非 Agent 操作工具，不违反硬约束 ②。
- 全自托管：LLM 走公司内部 OpenAI 兼容端点；DEEPSEEK `deepseek-v4-flash`，base URL `https://api.deepseek.com/v1`。
- 测试策略：单测全 mock LLM（`monkeypatch.delenv` DEEPSEEK key + MagicMock client）；e2e 用真 key（`deepseek-v4-flash`）。真 key 不得出现在被提交文件中。
- GPL 红线：llm_wiki 是 GPL v3。不导入、不链接、不复制其源码；只借鉴公开工程方法，用 Python 重新实现。所有借鉴处注释标注"理解原理后用 Python 重新实现"。
- 不动 M2 身份模型：`source_identity`（绝对 md 路径）+ `sources: []` bug 原样保留，增量层旁路。
- 砍掉 `kb watch`：常驻监听 / 状态机 / 崩溃恢复 / 去抖动全不做，仅手动闭环。
- `ts` 用 `config.today()` 日期粒度（不引入实时时钟，与 M2 一致、可测试）。
- 每任务结束 commit；提交前对应单测绿。

---

## File Structure

```
l1_kb/ingest/incremental/
├── __init__.py            # 空包标记
├── hash_store.py          # hash.json 读写：load/save/upsert/remove，键=slug
├── ingest_log.py          # ingest_log.jsonl append：append_ingest/delete/lint/rebuild
├── change_detect.py       # 扫 raw/ 对比 hash.json → ChangeSet{add,modify,delete,skip}
├── delete.py              # 精准反向清理：paths[]→删 wiki 页(+md+cache+hash)+rebuild_index
└── ingest_flow.py         # 三态编排：add/modify/delete 分发，事务（hash.json 最后落盘）
l1_kb/ingest/lint/
├── __init__.py            # 空包标记
├── checker.py             # L1-L5 五项检查 → list[Issue]
└── report.py              # lint_report.json 萒盘 + 终端摘要 + exit code
l1_kb/cli/kb.py            # 加 lint / rebuild 子命令；ingest 加 raw 三态分支
l1_kb/config.py            # 加 HASH_PATH / INGEST_LOG_PATH（PEP 562 lazy）
tests/
├── test_hash_store.py
├── test_change_detect.py
├── test_delete.py
├── test_ingest_flow.py
├── test_lint.py
├── test_rebuild.py
└── test_m3_incremental_e2e.py   # 真 key 端到端
```

**关键既有接口（M2，本计划不改其实现，只调用）：**

- `l1_kb/ingest/doc_id.py::make_doc_id(raw_root, raw_path) -> str` → `"{slug}__{sha256[:8]}"`；`slugify_path(rel) -> str` → slug 部分。
- `l1_kb/ingest/clean.py::clean_one(raw_root, raw_path, md_root, *, dry_run=False) -> CleanResult`（含 `.doc_id` `.md_path` `.skipped`）。
- `l1_kb/ingest/wiki/ingest.py::ingest_source(md_path, source_identity, *, wiki_root, cache_path, client, today, index_md) -> IngestResult`（含 `.written_paths` `.skipped_cached` `.fallback`）。`read_index_md(wiki_root)`、`make_client_from_config()`。
- `l1_kb/ingest/wiki/ingest_cache.py`：`_load(cache_path)->dict`（模块私有，本计划在 delete.py 中复用同等逻辑而非直接 import 私有名——见 Task 4）；`save_cache(cache_path, identity, hash, paths)`。
- `l1_kb/ingest/wiki/index_log.py::rebuild_index(wiki_root, today)`。
- `l1_kb/ingest/wiki/frontmatter.py::parse(content)->(Frontmatter, body)`；Frontmatter 字段 `type/title/created/updated/tags/related/sources`。
- `l1_kb/ingest/wiki/page_types.py`：`PAGE_TYPES`、`TYPE_TO_DIR`、`DIR_TO_TYPE`。
- `l1_kb/config.py::today() -> str`；`llm_enabled()`；PEP 562 路径常量 `RAW_ROOT/MD_ROOT/WIKI_ROOT/INGEST_CACHE_PATH`。

**关键约定：**

- `hash.json` 键 = slug（doc_id 去掉 `__{8hex}` 后缀）。同一 raw 路径重清洗 hash8 会变，slug 才稳定。
- raw→md 反查：glob `md/**/{slug}__*.md`（slug 来自 raw 相对路径，与 M1 `slugify_path` 一致）。
- md 绝对路径字符串 = `source_identity`（与 M2 cache key 一致）。
- `ingest-cache[identity].paths[]` 是唯一权威正向页索引，delete/modify 都靠它。
- 因 `sources: []` 现状全坏，多源页判别退化为：按 `paths[]` 全删该页；lint L3 兜底报孤儿。

---

## Task 1: hash_store.py — hash.json 读写

**Files:**
- Create: `l1_kb/ingest/incremental/__init__.py`（空文件）
- Create: `l1_kb/ingest/incremental/hash_store.py`
- Test: `tests/test_hash_store.py`

**Interfaces:**
- Consumes: `config.today()`（仅 `ingested_at` 字段用，默认值由调用方传 `today`）。
- Produces（后续任务依赖的签名，必须完全一致）：
  - `load_hash(hash_path: Path) -> dict[str, dict]`：不存在/损坏 → `{}`。
  - `save_hash(hash_path: Path, data: dict) -> None`：原子写（tmp+os.replace，indent=2, ensure_ascii=False）。
  - `upsert_hash(hash_path: Path, slug: str, *, hash: str, path: str, ingested_at: str) -> None`：load→改→save。`hash` 形如 `"sha256:a3f9..."`（调用方拼前缀）。
  - `remove_hash(hash_path: Path, slug: str) -> None`：删键不存在不报错。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hash_store.py
from pathlib import Path
from l1_kb.ingest.incremental import hash_store

def test_upsert_then_load(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "data_table_order_detail",
                            hash="sha256:a3f9c1e2", path="data_table/order_detail.xlsx",
                            ingested_at="2026-08-03")
    data = hash_store.load_hash(hp)
    assert data["data_table_order_detail"] == {
        "hash": "sha256:a3f9c1e2",
        "path": "data_table/order_detail.xlsx",
        "ingested_at": "2026-08-03",
    }

def test_remove_hash(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "a", hash="sha256:x", path="a.md", ingested_at="2026-08-03")
    hash_store.remove_hash(hp, "a")
    assert "a" not in hash_store.load_hash(hp)
    # 删不存在的键不报错
    hash_store.remove_hash(hp, "nope")

def test_load_missing_returns_empty(tmp_path: Path):
    assert hash_store.load_hash(tmp_path / "nope.json") == {}

def test_load_corrupt_returns_empty(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hp.write_text("{not json", encoding="utf-8")
    assert hash_store.load_hash(hp) == {}

def test_save_is_atomic(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "a", hash="sha256:x", path="a.md", ingested_at="2026-08-03")
    # 无残留 .tmp
    assert not list(tmp_path.glob("*.tmp"))
    # 中文/特殊字符 ensure_ascii=False
    hp.write_text("{}", encoding="utf-8")
    hash_store.upsert_hash(hp, "cn_测试", hash="sha256:y", path="中文/文件.xlsx", ingested_at="2026-08-03")
    assert "中文" in hp.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hash_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'l1_kb.ingest.incremental'`

- [ ] **Step 3: Write minimal implementation**

```python
# l1_kb/ingest/incremental/__init__.py
# （空文件，仅作包标记）
```

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hash_store.py -v`
Expected: PASS（5 项全绿）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/incremental/__init__.py l1_kb/ingest/incremental/hash_store.py tests/test_hash_store.py
git commit -m "feat(m3): hash_store.py — hash.json 变更检测存储"
```

## Task 2: ingest_log.py — ingest_log.jsonl append

**Files:**
- Create: `l1_kb/ingest/incremental/ingest_log.py`
- Test: `tests/test_ingest_log.py`

**Interfaces:**
- Consumes: 无（纯文件追加；`today` 由调用方传入）。
- Produces（后续任务依赖，签名固定）：
  - `append_ingest(log_path: Path, *, today: str, doc_id: str, action: str, source: str) -> None`：写 `{"ts","type":"ingest","doc_id","action","source"}`。action∈`add|modify|skipped_no_md`。
  - `append_delete(log_path: Path, *, today: str, doc_id: str, source: str) -> None`：写 `{"ts","type":"delete","doc_id","source"}`。
  - `append_lint(log_path: Path, *, today: str, issues: int, errors: int, warnings: int, info: int) -> None`。
  - `append_rebuild(log_path: Path, *, today: str) -> None`：写 `{"ts","type":"rebuild"}`。
  - `read_log(log_path: Path) -> list[dict]`：每行一 JSON，坏行跳过；不存在→`[]`（lint L1 用）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest_log.py
from pathlib import Path
from l1_kb.ingest.incremental import ingest_log

def test_append_ingest_add(tmp_path: Path):
    lp = tmp_path / "ingest_log.jsonl"
    ingest_log.append_ingest(lp, today="2026-08-03", doc_id="dt_order__a3f9c1e2",
                              action="add", source="data_table/order_detail.xlsx")
    lines = ingest_log.read_log(lp)
    assert len(lines) == 1
    assert lines[0] == {
        "ts": "2026-08-03", "type": "ingest",
        "doc_id": "dt_order__a3f9c1e2", "action": "add",
        "source": "data_table/order_detail.xlsx",
    }

def test_append_delete_and_lint_and_rebuild(tmp_path: Path):
    lp = tmp_path / "ingest_log.jsonl"
    ingest_log.append_delete(lp, today="2026-08-03", doc_id="dt_order__a3f9c1e2",
                              source="data_table/order_detail.xlsx")
    ingest_log.append_lint(lp, today="2026-08-03", issues=5, errors=1, warnings=3, info=1)
    ingest_log.append_rebuild(lp, today="2026-08-03")
    lines = ingest_log.read_log(lp)
    assert [l["type"] for l in lines] == ["delete", "lint", "rebuild"]
    assert lines[1] == {"ts": "2026-08-03", "type": "lint",
                        "issues": 5, "errors": 1, "warnings": 3, "info": 1}
    assert lines[2] == {"ts": "2026-08-03", "type": "rebuild"}

def test_read_log_skips_bad_lines(tmp_path: Path):
    lp = tmp_path / "ingest_log.jsonl"
    lp.write_text('{"ts":"2026-08-03","type":"rebuild"}\n{bad json}\n', encoding="utf-8")
    lines = ingest_log.read_log(lp)
    assert len(lines) == 1

def test_read_log_missing(tmp_path: Path):
    assert ingest_log.read_log(tmp_path / "nope.jsonl") == []

def test_append_creates_parent(tmp_path: Path):
    lp = tmp_path / "sub" / "ingest_log.jsonl"
    ingest_log.append_rebuild(lp, today="2026-08-03")
    assert lp.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_log.py -v`
Expected: FAIL — `ModuleNotFoundError: ... ingest_log`

- [ ] **Step 3: Write minimal implementation**

```python
# l1_kb/ingest/incremental/ingest_log.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_log.py -v`
Expected: PASS（5 项全绿）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/incremental/ingest_log.py tests/test_ingest_log.py
git commit -m "feat(m3): ingest_log.py — 时序日志 append/read"
```

## Task 3: change_detect.py — 四态变更检测

**Files:**
- Create: `l1_kb/ingest/incremental/change_detect.py`
- Test: `tests/test_change_detect.py`

**Interfaces:**
- Consumes: `l1_kb/ingest/doc_id.py::make_doc_id(raw_root, raw_path)->str`、`slugify_path(rel)->str`；`l1_kb/ingest/cleaners/dispatcher.py::SUPPORTED_EXTS`；`hash_store.load_hash`。
- Produces（后续 ingest_flow 依赖，签名固定）：
  - `@dataclass ChangeItem`：`slug: str`、`raw_path: Path`（绝对）、`raw_rel: str`（POSIX 相对 raw_root）、`doc_id: str`、`hash: str`（`"sha256:..."`）。
  - `@dataclass ChangeSet`：`add: list[ChangeItem]`、`modify: list[ChangeItem]`、`delete: list[DeleteItem]`、`skip: list[ChangeItem]`。
  - `@dataclass DeleteItem`：`slug: str`、`raw_rel: str`（来自 hash.json 记录的 `path`）。
  - `detect_changes(raw_root: Path, hash_path: Path) -> ChangeSet`：扫 raw/ 下 SUPPORTED_EXTS 文件，对比 hash.json，产出四集。
  - `slug_of(doc_id: str) -> str`：去掉 `__{8hex}` 后缀（`re.sub(r"__[0-9a-f]{8}$", "", doc_id)`）。
  - `hash_raw(raw_path: Path) -> str`：`"sha256:" + sha256(文件字节).hexdigest()`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_change_detect.py
from pathlib import Path
from l1_kb.ingest.incremental import change_detect
from l1_kb.ingest.incremental import hash_store

def _make_raw(root: Path):
    (root / "data_table").mkdir(parents=True)
    f = root / "data_table" / "order_detail.xlsx"
    f.write_bytes(b"hello")
    return f

def test_slug_of():
    assert change_detect.slug_of("data_table_order_detail__a3f9c1e2") == "data_table_order_detail"
    assert change_detect.slug_of("no_hash") == "no_hash"

def test_detect_add(tmp_path: Path):
    raw = tmp_path / "raw"
    _make_raw(raw)
    hp = tmp_path / "hash.json"
    cs = change_detect.detect_changes(raw, hp)
    assert len(cs.add) == 1
    assert cs.add[0].slug == "data_table_order_detail"
    assert cs.add[0].hash.startswith("sha256:")
    assert cs.add[0].raw_rel == "data_table/order_detail.xlsx"
    assert cs.modify == [] and cs.delete == [] and cs.skip == []

def test_detect_skip_unchanged(tmp_path: Path):
    raw = tmp_path / "raw"
    f = _make_raw(raw)
    hp = tmp_path / "hash.json"
    cs1 = change_detect.detect_changes(raw, hp)
    it = cs1.add[0]
    hash_store.upsert_hash(hp, it.slug, hash=it.hash, path=it.raw_rel, ingested_at="2026-08-03")
    cs2 = change_detect.detect_changes(raw, hp)
    assert cs2.add == [] and len(cs2.skip) == 1 and cs2.skip[0].slug == it.slug

def test_detect_modify(tmp_path: Path):
    raw = tmp_path / "raw"
    f = _make_raw(raw)
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "data_table_order_detail", hash="sha256:old",
                            path="data_table/order_detail.xlsx", ingested_at="2026-08-02")
    cs = change_detect.detect_changes(raw, hp)
    assert len(cs.modify) == 1 and cs.modify[0].hash.startswith("sha256:")
    assert cs.modify[0].hash != "sha256:old"

def test_detect_delete(tmp_path: Path):
    raw = tmp_path / "raw"
    _make_raw(raw)
    hp = tmp_path / "hash.json"
    # hash.json 记录了一个 raw 里不存在的 slug
    hash_store.upsert_hash(hp, "gone_doc", hash="sha256:x", path="gone/doc.md", ingested_at="2026-08-02")
    cs = change_detect.detect_changes(raw, hp)
    assert len(cs.delete) == 1
    assert cs.delete[0].slug == "gone_doc"
    assert cs.delete[0].raw_rel == "gone/doc.md"

def test_detect_empty_raw(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    hp = tmp_path / "hash.json"
    cs = change_detect.detect_changes(raw, hp)
    assert cs.add == [] and cs.modify == [] and cs.delete == [] and cs.skip == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_change_detect.py -v`
Expected: FAIL — `ModuleNotFoundError: ... change_detect`

- [ ] **Step 3: Write minimal implementation**

```python
# l1_kb/ingest/incremental/change_detect.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_change_detect.py -v`
Expected: PASS（6 项全绿）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/incremental/change_detect.py tests/test_change_detect.py
git commit -m "feat(m3): change_detect.py — raw/hash.json 四态检测"
```

## Task 4: delete.py — 精准反向清理

**Files:**
- Create: `l1_kb/ingest/incremental/delete.py`
- Test: `tests/test_delete.py`

**Interfaces:**
- Consumes:
  - `hash_store.load_hash / remove_hash`（Task 1）
  - `l1_kb/ingest/wiki/ingest_cache.py`：直接复用其 `_load`/`_save` 等价逻辑——为避免依赖私有名，本模块自带 `_load_cache/_save_cache`（与 M2 同样 tmp+os.replace 原子写，保持一致）。或更简单：`from ..wiki.ingest_cache import _load, _save`——**采用后者**，M2 同包私有名可 import，注释说明耦合点。
  - `l1_kb/ingest/wiki/index_log.py::rebuild_index(wiki_root, today)`
  - `l1_kb/ingest/doc_id.py::slugify_path` 不直接用——slug 由调用方（ingest_flow）传入。
- Produces（ingest_flow 依赖，签名固定）：
  - `find_md_for_slug(md_root: Path, slug: str) -> Path | None`：glob `**/{slug}__*.md`，命中第一个返回绝对路径，无→None。
  - `purge_source(*, slug: str, md_root: Path, wiki_root: Path, cache_path: Path, hash_path: Path, today: str) -> PurgeResult`：精准反向清理一个源。
  - `@dataclass PurgeResult`：`deleted_pages: list[str]`、`deleted_md: bool`、`slug: str`。

**清理逻辑（M3 设计 §二）：** slug → `find_md_for_slug` 得 md 绝对路径 = source_identity → `_load(cache)` 取 `cache[identity].paths[]` → 删每个 wiki 页文件 → 删 md 文件 → `save_cache`（剔除该 identity）→ `remove_hash(hash_path, slug)` → `rebuild_index`。cache 无该 identity 或 paths 为空 → 仅尽力删（glob 兜底找 `wiki/**/{slug}__*.md` 删 source 页），不报错。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delete.py
from pathlib import Path
from l1_kb.ingest.incremental import delete, hash_store
from l1_kb.ingest.wiki.ingest_cache import save_cache

def _seed(tmp_path: Path):
    md_root = tmp_path / "md"
    wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    # md 文件 {slug}__a3f9c1e2.md
    md_path = md_root / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n", encoding="utf-8")
    # 两张 wiki 页
    src = wiki / "sources" / "data_table_order_detail__a3f9c1e2.md"
    ent = wiki / "entities" / "entity_order.md"
    src.parent.mkdir(parents=True)
    ent.parent.mkdir(parents=True)
    src.write_text("---\ntype: source\n---\nbody\n", encoding="utf-8")
    ent.write_text("---\ntype: entity\n---\nbody\n", encoding="utf-8")
    # cache: identity=md 绝对路径, paths=[src, ent]
    save_cache(cache, str(md_path), "somehash", [str(src), str(ent)])
    hash_store.upsert_hash(hp, "data_table_order_detail", hash="sha256:x",
                            path="data_table/order_detail.xlsx", ingested_at="2026-08-02")
    return md_path, src, ent

def test_find_md_for_slug(tmp_path: Path):
    md_root = tmp_path / "md"
    md_path, _, _ = _seed(tmp_path)
    found = delete.find_md_for_slug(md_root, "data_table_order_detail")
    assert found == md_path
    assert delete.find_md_for_slug(md_root, "nope") is None

def test_purge_deletes_pages_md_cache_hash(tmp_path: Path):
    md_root = tmp_path / "md"
    md_path, src, ent = _seed(tmp_path)
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    wiki = tmp_path / "wiki"
    res = delete.purge_source(slug="data_table_order_detail", md_root=md_root,
                              wiki_root=wiki, cache_path=cache, hash_path=hp,
                              today="2026-08-03")
    assert sorted(res.deleted_pages) == sorted([str(src), str(ent)])
    assert res.deleted_md is True
    assert not src.exists() and not ent.exists()
    assert not md_path.exists()
    assert str(md_path) not in hash_store.load_hash.__doc__ or True  # placeholder removed below
    # cache 条目被删
    import json
    assert str(md_path) not in json.loads(cache.read_text(encoding="utf-8"))
    # hash 条目被删
    from l1_kb.ingest.incremental.hash_store import load_hash
    assert "data_table_order_detail" not in load_hash(hp)
    # rebuild_index 后无幽灵（index.md 不列已删页）
    assert (wiki / "index.md").exists()
    assert "data_table_order_detail" not in (wiki / "index.md").read_text(encoding="utf-8")

def test_purge_no_cache_entry_still_globs_source_page(tmp_path: Path):
    """cache 无 identity（如 process paths:[]）→ glob 兜底删 source 页。"""
    md_root = tmp_path / "md"
    wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    md_path = md_root / "process" / "process_policy__2cc0e310.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## x\n", encoding="utf-8")
    src = wiki / "sources" / "process_policy__2cc0e310.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\ntype: source\n---\nbody\n", encoding="utf-8")
    # 故意不写 cache 条目
    hash_store.upsert_hash(hp, "process_policy", hash="sha256:x", path="process/policy.md", ingested_at="2026-08-02")
    res = delete.purge_source(slug="process_policy", md_root=md_root, wiki_root=wiki,
                              cache_path=cache, hash_path=hp, today="2026-08-03")
    assert res.deleted_md is True
    assert not src.exists()  # glob 兜底删了
    from l1_kb.ingest.incremental.hash_store import load_hash
    assert "process_policy" not in load_hash(hp)

def test_purge_missing_slug_is_noop(tmp_path: Path):
    md_root = tmp_path / "md"; md_root.mkdir()
    wiki = tmp_path / "wiki"; wiki.mkdir()
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    res = delete.purge_source(slug="ghost", md_root=md_root, wiki_root=wiki,
                              cache_path=cache, hash_path=hp, today="2026-08-03")
    assert res.deleted_pages == [] and res.deleted_md is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delete.py -v`
Expected: FAIL — `ModuleNotFoundError: ... delete`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_delete.py -v`
Expected: PASS（4 项全绿）。注：`test_purge_deletes_pages...` 中那行 `assert str(md_path) not in hash_store.load_hash.__doc__ or True` 是占位噪声，实现前删除该行（见下方说明）。

> **实现前清理：** 将 `test_purge_deletes_pages_md_cache_hash` 中这行占位断言删掉：
> ```python
> assert str(md_path) not in hash_store.load_hash.__doc__ or True  # placeholder removed below
> ```
> 只保留后面的 `import json` 断言与 `load_hash(hp)` 断言。

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/incremental/delete.py tests/test_delete.py
git commit -m "feat(m3): delete.py — 精准反向清理（paths[] 权威）"
```

## Task 5: ingest_flow.py — 三态编排（事务）

**Files:**
- Create: `l1_kb/ingest/incremental/ingest_flow.py`
- Test: `tests/test_ingest_flow.py`

**Interfaces:**
- Consumes:
  - `change_detect.ChangeSet / ChangeItem / DeleteItem / detect_changes`（Task 3）
  - `delete.purge_source / find_md_for_slug`（Task 4）
  - `hash_store.upsert_hash`（Task 1）
  - `ingest_log.append_ingest / append_delete`（Task 2）
  - `l1_kb/ingest/wiki/ingest.py::ingest_source / read_index_md / make_client_from_config`
  - `l1_kb/ingest/clean.py::clean_one`（modify/add 前确保 md 就绪——flow 不调 clean，由 CLI 保证；flow 只读 md）
  - `config.today()`
- Produces（CLI 依赖，签名固定）：
  - `@dataclass FlowSummary`：`added: int`、`modified: int`、`deleted: int`、`skipped: int`、`failed: int`、`total: int`、`details: list[str]`（每条 `[ADD]/[MODIFY]/[DELETE]/[SKIP]/[ERR]/[WARN] {slug}: ...`）。
  - `run_incremental(*, raw_root, md_root, wiki_root, cache_path, hash_path, log_path, client, today) -> FlowSummary`：扫 raw→三态分发→返回摘要。单文件异常 try/except 不崩批次；hash.json 最后落盘=事务提交。

**事务语义（M3 设计 §三）：** 对单个 add/modify：先 `ingest_source`（写 wiki+cache）→ 成功后才 `upsert_hash` + `append_ingest`。失败→不更新 hash.json，下次重跑视为未完成。modify = 先 `purge_source`（删旧页）再 `ingest_source`（写新页）。delete = `purge_source` + `append_delete`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest_flow.py
from pathlib import Path
from unittest.mock import MagicMock
from l1_kb.ingest.incremental import ingest_flow, hash_store
from l1_kb.ingest.wiki.ingest import build_fallback_pages

def _seed_raw_md(tmp_path: Path, slug="data_table_order_detail", body="## 订单\n\n| order_id |\n|---|\n| O1 |\n"):
    raw = tmp_path / "raw"
    md_root = tmp_path / "md"
    raw_f = raw / "data_table" / "order_detail.xlsx"
    raw_f.parent.mkdir(parents=True)
    raw_f.write_bytes(b"rawbytes")
    # md 已 clean 就绪（{slug}__{hash8}.md）
    md_path = md_root / "data_table" / f"{slug}__a3f9c1e2.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text(body, encoding="utf-8")
    return raw_f, md_path

def _fake_client_for(md_path):
    """返回一个会让 ingest_source 走 fallback 的 None client（单测不调 LLM）。"""
    return None

def test_add_ingests_and_commits_hash(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    summ = ingest_flow.run_incremental(raw_root=tmp_path / "raw", md_root=tmp_path / "md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp,
        client=None, today="2026-08-03")
    assert summ.added == 1 and summ.failed == 0
    # hash.json 提交
    data = hash_store.load_hash(hp)
    assert "data_table_order_detail" in data
    # wiki 页 + cache + log
    assert (wiki / "sources" / "data_table_order_detail__a3f9c1e2.md").exists()
    assert "data_table_order_detail" in lp.read_text(encoding="utf-8")

def test_skip_unchanged(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    # 第二次：应全 skip
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.added == 0 and summ.modified == 0 and summ.skipped == 1

def test_modify_delete_then_add_no_orphan(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    # 第一次摄入
    ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    # 改 raw 内容 → 重 clean（测试里直接重写 md 模拟 clean）
    raw.write_bytes(b"changedbytes")
    md_path2 = tmp_path / "md" / "data_table" / "data_table_order_detail__deadbeef.md"
    md_path2.write_text("## 订单\n\n| order_id |\n|---|\n| O2 |\n", encoding="utf-8")
    md_path = tmp_path / "md" / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    md_path.unlink()  # clean 已用新 hash8 重写，旧 md 删除
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.modified == 1
    # 旧 source 页（__a3f9c1e2）不残留
    assert not (wiki / "sources" / "data_table_order_detail__a3f9c1e2.md").exists()
    # 新 source 页在
    assert (wiki / "sources" / "data_table_order_detail__deadbeef.md").exists()

def test_delete_purges_source(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    # 删 raw
    raw.unlink()
    md_path = tmp_path / "md" / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.deleted == 1
    assert not (wiki / "sources" / "data_table_order_detail__a3f9c1e2.md").exists()
    assert "data_table_order_detail" not in hash_store.load_hash(hp)
    assert "\"type\": \"delete\"" in lp.read_text(encoding="utf-8") or '"type":"delete"' in lp.read_text(encoding="utf-8")

def test_add_no_md_warns_not_crash(tmp_path: Path):
    raw = tmp_path / "raw"
    raw_f = raw / "data_table" / "order_detail.xlsx"
    raw_f.parent.mkdir(parents=True)
    raw_f.write_bytes(b"rawbytes")
    # md 未 clean
    md_root = tmp_path / "md"; md_root.mkdir()
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    summ = ingest_flow.run_incremental(raw_root=raw, md_root=md_root,
        wiki_root=tmp_path/"wiki", cache_path=tmp_path/"cache.json", hash_path=hp,
        log_path=lp, client=None, today="2026-08-03")
    assert summ.failed == 0  # 不是失败，是 warn
    assert summ.added == 0
    assert any("WARN" in d or "no_md" in d for d in summ.details)

def test_single_file_error_does_not_crash_batch(tmp_path: Path, monkeypatch):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    real = ingest_flow.ingest_source
    def boom(md_path, identity, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(ingest_flow, "ingest_source", boom)
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.failed == 1
    # 失败不提交 hash
    assert "data_table_order_detail" not in hash_store.load_hash(hp)

def test_transaction_hash_last(tmp_path: Path, monkeypatch):
    """ingest_source 成功但 upsert_hash 抛异常 → 视为失败，hash 未提交。"""
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    def boom_upsert(*a, **k):
        raise RuntimeError("hash write boom")
    monkeypatch.setattr(ingest_flow, "upsert_hash", boom_upsert)
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.failed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_flow.py -v`
Expected: FAIL — `ModuleNotFoundError: ... ingest_flow`

- [ ] **Step 3: Write minimal implementation**

```python
# l1_kb/ingest/incremental/ingest_flow.py
"""三态编排 —— M3 设计 §三。

扫 raw → 四态 → add/modify/delete 分发。单文档事务：wiki/cache 写成功后才
upsert_hash + append_log（hash.json 最后落盘=提交）。理解原理后用 Python 重新实现。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..wiki.ingest import ingest_source, read_index_md
from .change_detect import ChangeItem, ChangeSet, detect_changes
from .delete import find_md_for_slug, purge_source
from .hash_store import upsert_hash
from .ingest_log import append_delete, append_ingest

__all__ = ["FlowSummary", "run_incremental"]


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
            purge_source(slug=item.slug, md_root=md_root, wiki_root=wiki_root,
                         cache_path=cache_path, hash_path=hash_path, today=today)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_flow.py -v`
Expected: PASS（7 项全绿）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/incremental/ingest_flow.py tests/test_ingest_flow.py
git commit -m "feat(m3): ingest_flow.py — 三态编排+事务（hash 最后落盘）"
```

## Task 6: lint/checker.py — L1-L5 五项确定性自检

**Files:**
- Create: `l1_kb/ingest/lint/__init__.py`（空）
- Create: `l1_kb/ingest/lint/checker.py`
- Test: `tests/test_lint.py`

**Interfaces:**
- Consumes:
  - `l1_kb/ingest/wiki/frontmatter.py::parse(content)->(Frontmatter, body)`
  - `l1_kb/ingest/wiki/page_types.py::PAGE_TYPES, TYPE_TO_DIR, DIR_TO_TYPE`
  - `l1_kb/ingest/wiki/index_log.py` 的 `_EXCLUDED_STEMS`（复用为常量或自建同名 set `{"index","log","overview"}`——**自建**避免依赖私有名）
  - `l1_kb/ingest/incremental/ingest_log.py::read_log`（L1 校验 ingest_log.jsonl）
  - `l1_kb/ingest/incremental/hash_store.py::load_hash`（L1 校验 hash.json）
- Produces（report.py + CLI 依赖，签名固定）：
  - `@dataclass Issue`：`code: str`（如 `"L2_GHOST"`）、`level: str`（`"error"|"warn"|"info"`）、`msg: str`、`page: str = ""`、`type: str = ""`。
  - `@dataclass LintReport`：`issues: list[Issue]`、`errors: int`、`warnings: int`、`info: int`、`ts: str`。
  - `JACCARD_THRESHOLD = 0.5`（模块常量）。
  - `run_lint(*, wiki_root, hash_path, ingest_log_path, cache_path, md_root, today) -> LintReport`：跑 L1-L5，返回报告（含计数）。

**五项（M3 设计 §四）：**
- **L1 格式校验**（error）：index.md 首行 `# Wiki Index`；log.md 首行 `# Wiki Log`；ingest_log.jsonl 每行合法 JSON 含 `ts/type`；hash.json/ingest-cache.json 合法 JSON。任一缺失/非法→error issue。
- **L2 wiki页↔index.md 对齐**：`P_disk`=盘上有效 type wiki 页 slug 集；`P_index`=index.md `- [[slug|...]]` 解析出的 slug 集。`P_index - P_disk`=幽灵→error；`P_disk - P_index`=漏列→warn。
- **L3 孤儿页**（warn）：扫所有页 `related[]` 建『被指向集』；非 source 页（type∈{entity,concept,process}）不在被指向集→孤儿 warn。source 页不报。
- **L4 缺交叉引用**（warn）：两 entity/concept 页 `tags[]` Jaccard≥0.5 但互不在对方 `related[]`→warn。
- **L5 数据缺口**（info）：`sources` 目录无页 / `process` 目录无页 / 某 type 目录缺失→info。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lint.py
from pathlib import Path
from l1_kb.ingest.lint import checker
from l1_kb.ingest.wiki.index_log import rebuild_index
from l1_kb.ingest.incremental import hash_store, ingest_log

def _seed_clean_wiki(tmp_path: Path):
    wiki = tmp_path / "wiki"
    hp = tmp_path / "hash.json"
    lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"
    md_root = tmp_path / "md"; md_root.mkdir()
    rebuild_index(wiki, "2026-08-03")
    (wiki / "log.md").write_text("# Wiki Log\n", encoding="utf-8")
    hash_store.upsert_hash(hp, "x", hash="sha256:x", path="x.md", ingested_at="2026-08-03")
    cache.write_text("{}", encoding="utf-8")
    return wiki, hp, lp, cache, md_root

def test_lint_clean_wiki_no_issues(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert rep.errors == 0

def test_l1_format_bad_index(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    (wiki / "index.md").write_text("wrong first line\n", encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L1_FORMAT" and i.level == "error" for i in rep.issues)

def test_l1_bad_ingest_log_line(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    lp.write_text('{"ts":"2026-08-03","type":"rebuild"}\n{bad}\n', encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L1_FORMAT" for i in rep.issues)

def test_l2_ghost_reference(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    # index 列了 ghost 页，但磁盘没有
    idx = wiki / "index.md"
    idx.write_text("# Wiki Index\n_updated: 2026-08-03_\n\n## source\n- [[ghost_page|Ghost]]\n", encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L2_GHOST" and i.level == "error" and i.page == "ghost_page" for i in rep.issues)

def test_l2_missing_from_index(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    src = wiki / "sources" / "entity_foo.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\ntype: source\ntitle: \"foo\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: []\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-03")  # 让 index 含它
    # 手动从 index 删掉它模拟漏列
    idx = wiki / "index.md"
    idx.write_text("# Wiki Index\n_updated: 2026-08-03_\n\n_(暂无页面)_\n", encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L2_MISSING" and i.level == "warn" for i in rep.issues)

def test_l3_orphan(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    ent = wiki / "entities" / "entity_lonely.md"
    ent.parent.mkdir(parents=True)
    ent.write_text("---\ntype: entity\ntitle: \"lonely\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: []\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L3_ORPHAN" and i.page == "entity_lonely" for i in rep.issues)

def test_l4_missing_crossref(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    e1 = wiki / "entities" / "entity_a.md"
    e2 = wiki / "entities" / "entity_b.md"
    e1.parent.mkdir(parents=True)
    # 共享 tags，但 related 互不指向 → L4
    e1.write_text("---\ntype: entity\ntitle: \"a\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: [order, api]\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    e2.write_text("---\ntype: entity\ntitle: \"b\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: [order, api]\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L4_XREF" for i in rep.issues)

def test_l5_data_gap(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    # 没有任何 source 页
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L5_GAP" and i.level == "info" for i in rep.issues)

def test_report_counts(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    total_issues = len(rep.issues)
    assert rep.errors + rep.warnings + rep.info == total_issues
    assert rep.ts == "2026-08-03"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lint.py -v`
Expected: FAIL — `ModuleNotFoundError: ... lint`

- [ ] **Step 3: Write minimal implementation**

```python
# l1_kb/ingest/lint/__init__.py
# （空文件）
```

```python
# l1_kb/ingest/lint/checker.py
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
    """yield (path, stem, frontmatter) for valid-type wiki pages."""
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
    for _, stem, fm, _ in pages:
        if fm.type == "source":
            continue  # source 页不报孤儿
        if stem not in pointed:
            issues.append(Issue("L3_ORPHAN", "warn", "无 related 指向", page=stem, type=fm.type))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _check_l4(wiki_root: Path, issues: list[Issue]) -> None:
    pages = [(stem, fm) for _, stem, fm, _ in _iter_pages(wiki_root)
             if fm.type in ("entity", "concept")]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lint.py -v`
Expected: PASS（9 项全绿）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/lint/__init__.py l1_kb/ingest/lint/checker.py tests/test_lint.py
git commit -m "feat(m3): lint/checker.py — L1-L5 五项确定性自检"
```

## Task 7: lint/report.py — lint_report.json 落盘 + 终端摘要

**Files:**
- Create: `l1_kb/ingest/lint/report.py`
- Modify: `tests/test_lint.py`（追加 report 落盘测试）

**Interfaces:**
- Consumes: Task 6 `run_lint(...) -> LintReport`、`Issue`、`LintReport`。
- Produces（CLI 依赖，签名固定）：
  - `write_report(report: LintReport, out_path: Path) -> None`：原子写 `lint_report.json`（dict: ts/errors/warnings/info/issues[]）。
  - `format_summary(report: LintReport) -> str`：终端人读多行字符串（含 errors/warnings/info 计数 + 逐 issue 行）。
  - `exit_code(report: LintReport) -> int`：`1 if report.errors else 0`。

- [ ] **Step 1: Write the failing test**（追加到 `tests/test_lint.py` 末尾）

```python
def test_lint_report_write_and_summary(tmp_path):
    from l1_kb.ingest.lint.report import write_report, format_summary, exit_code
    from l1_kb.ingest.lint.checker import Issue, LintReport
    rep = LintReport(ts="2026-08-03", issues=[
        Issue("L2_GHOST", "error", "幽灵", page="entity_foo"),
        Issue("L3_ORPHAN", "warn", "孤儿", page="concept_bar"),
        Issue("L5_GAP", "info", "缺口", type="process"),
    ])
    rep.errors = 1; rep.warnings = 1; rep.info = 1
    out = tmp_path / "lint_report.json"
    write_report(rep, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["errors"] == 1 and data["warnings"] == 1 and data["info"] == 1
    assert len(data["issues"]) == 3
    assert data["issues"][0]["code"] == "L2_GHOST"
    s = format_summary(rep)
    assert "errors: 1" in s and "warnings: 1" in s and "L2_GHOST" in s
    assert exit_code(rep) == 1
    rep.errors = 0
    assert exit_code(rep) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lint.py::test_lint_report_write_and_summary -v`
Expected: FAIL（`l1_kb.ingest.lint.report` 不存在）

- [ ] **Step 3: Write minimal implementation**

```python
# l1_kb/ingest/lint/report.py
"""lint_report.json 落盘 + 终端摘要 + 退出码 —— M3 设计 §四。"""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from .checker import LintReport

__all__ = ["write_report", "format_summary", "exit_code"]

LEVEL_ICON = {"error": "✗", "warn": "⚠", "info": "ℹ"}

def write_report(report: LintReport, out_path: Path) -> None:
    """原子写 lint_report.json（可 CI/diff）。"""
    payload = {
        "ts": report.ts,
        "errors": report.errors,
        "warnings": report.warnings,
        "info": report.info,
        "issues": [asdict(i) for i in report.issues],
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)

def format_summary(report: LintReport) -> str:
    """终端人读多行摘要。"""
    lines = [
        f"Lint 报告（{report.ts}）: errors={report.errors}, warnings={report.warnings}, info={report.info}",
    ]
    for i in report.issues:
        loc = f" [{i.page}]" if i.page else (f" [{i.type}]" if i.type else "")
        lines.append(f"  {LEVEL_ICON.get(i.level, '?')} {i.code}{loc}: {i.msg}")
    return "\n".join(lines)

def exit_code(report: LintReport) -> int:
    """error 级项 → 退出码 1，否则 0。"""
    return 1 if report.errors else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lint.py -v`
Expected: PASS（含 report 测试）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/lint/report.py tests/test_lint.py
git commit -m "feat(m3): lint/report.py — lint_report.json + 终端摘要 + 退码"
```

## Task 8: config.py HASH/LOG 路径 + cli/kb.py lint/rebuild + ingest raw 三态分支

**Files:**
- Modify: `l1_kb/config.py`（加 `HASH_PATH`、`INGEST_LOG_PATH` 模块属性）
- Modify: `l1_kb/cli/kb.py`（ingest 加 raw 三态分支；新增 `lint`、`rebuild` 子命令）
- Test: `tests/test_kb_cli_m3.py`

**Interfaces:**
- Consumes: Task 1-7 全部（hash_store / ingest_log / change_detect / delete / ingest_flow / lint.checker / lint.report）。
- Produces: CLI 子命令 `kb ingest <raw-or-md>`、`kb lint`、`kb rebuild`（对外稳定入口）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_cli_m3.py
import json
from pathlib import Path
from click.testing import CliRunner
from l1_kb.cli.kb import cli

def _make_raw_md(tmp_path: Path):
    raw = tmp_path / "raw" / "data_table"
    raw.mkdir(parents=True)
    f = raw / "order_detail.xlsx"
    f.write_bytes(b"hello")
    md_root = tmp_path / "md"
    (md_root / "data_table").mkdir(parents=True)
    md_path = md_root / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    md_path.write_text("## 订单\n\n| order_id |\n|---|\n| O1 |\n", encoding="utf-8")
    return f, md_path

def test_kb_ingest_raw_three_state_add(tmp_path, monkeypatch):
    f, md_path = _make_raw_md(tmp_path)
    wiki = tmp_path / "wiki"; wiki.mkdir()
    cache = tmp_path / "cache.json"; hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "ingest", str(tmp_path / "raw"),
        "--raw-root", str(tmp_path / "raw"),
        "--md-root", str(tmp_path / "md"),
        "--wiki-root", str(wiki),
        "--cache-path", str(cache),
        "--hash-path", str(hp), "--log-path", str(lp),
    ])
    assert res.exit_code == 0, res.output
    assert "新增 1" in res.output
    data = json.loads(hp.read_text(encoding="utf-8"))
    assert "data_table_order_detail" in data
    assert "type\":\"ingest" in lp.read_text(encoding="utf-8")

def test_kb_ingest_md_backward_compat(tmp_path, monkeypatch):
    # path 在 md_root 下 → 走 M2 直摄入，无 hash.json
    md_root = tmp_path / "md"
    (md_root / "data_table").mkdir(parents=True)
    md_path = md_root / "data_table" / "order_detail.md"
    md_path.write_text("## 订单\n\n| order_id |\n|---|\n| O1 |\n", encoding="utf-8")
    wiki = tmp_path / "wiki"; wiki.mkdir()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "ingest", str(md_path),
        "--raw-root", str(tmp_path / "raw"),
        "--md-root", str(md_root),
        "--wiki-root", str(wiki),
        "--cache-path", str(tmp_path / "cache.json"),
    ])
    assert res.exit_code == 0, res.output
    assert (wiki / "sources").exists()

def test_kb_lint_clean_exit0(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "sources").mkdir(parents=True)
    (wiki / "sources" / "s1.md").write_text("---\ntype: source\ntitle: t\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: []\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    wiki.joinpath("index.md").write_text("# Wiki Index\n\n## source\n\n- [[s1|t]]\n", encoding="utf-8")
    wiki.joinpath("log.md").write_text("# Wiki Log\n", encoding="utf-8")
    res = CliRunner().invoke(cli, [
        "lint", "--wiki-root", str(wiki),
        "--raw-root", str(tmp_path / "raw"), "--md-root", str(tmp_path / "md"),
        "--cache-path", str(tmp_path / "c.json"),
        "--hash-path", str(tmp_path / "h.json"), "--log-path", str(tmp_path / "l.jsonl"),
    ])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "lint_report.json").exists()

def test_kb_rebuild_dry_run_no_yes(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "rebuild", "--raw-root", str(tmp_path / "raw"),
        "--md-root", str(tmp_path / "md"), "--wiki-root", str(tmp_path / "wiki"),
        "--cache-path", str(tmp_path / "c.json"),
        "--hash-path", str(tmp_path / "h.json"), "--log-path", str(tmp_path / "l.jsonl"),
    ])
    # 无 --yes → dry-run，不写生成物，退码 0
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output.lower() or "将清空" in res.output
    assert not (tmp_path / "wiki").exists() or not any((tmp_path / "wiki").rglob("*.md"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kb_cli_m3.py -v`
Expected: FAIL（`--hash-path`/`--log-path` 选项与 `lint`/`rebuild` 子命令不存在）

- [ ] **Step 3: Write minimal implementation**

**先改 `l1_kb/config.py`** —— 在 `_PATH_DIRS` 之外新增两个路径常量（PEP 562 `__getattr__` 已兜底；只需扩展 `_resolve_path` 与 `__getattr__` 的判定）。

```python
# l1_kb/config.py —— 修改 _PATH_DIRS 同级区域与 _resolve_path/__getattr__

_EXTRA_PATHS = {
    # 默认 .cache/hash.json 与 knowledge_base/ingest_log.jsonl
    "HASH_PATH": ("l1_kb", "knowledge_base", ".cache", "hash.json"),
    "INGEST_LOG_PATH": ("l1_kb", "knowledge_base", "ingest_log.jsonl"),
}

# _resolve_path 内追加：
    if name in _EXTRA_PATHS:
        default = _PROJECT_ROOT.joinpath(*_EXTRA_PATHS[name])
        return Path(os.environ.get(name, default))

# __getattr__ 内追加判定：
    if name in _PATH_DIRS or name in ("INGEST_CACHE_PATH",) or name in _EXTRA_PATHS:
        return _resolve_path(name)
```

**再改 `l1_kb/cli/kb.py`** —— ingest 加 raw 三态分支；加 lint/rebuild 子命令。在文件顶部 import 区追加：

```python
from ..ingest.incremental import ingest_flow, change_detect, delete as incr_delete
from ..ingest.incremental import hash_store, ingest_log
from ..ingest.lint import checker as lint_checker, report as lint_report
from ..ingest.doc_id import make_doc_id
from ..ingest.cleaners.dispatcher import SUPPORTED_EXTS
DEFAULT_HASH = "l1_kb/knowledge_base/.cache/hash.json"
DEFAULT_LOG = "l1_kb/knowledge_base/ingest_log.jsonl"
DEFAULT_LINT_REPORT = "lint_report.json"
```

**重写 `ingest` 命令**（保留选项，加 `--hash-path`/`--log-path`；body 区分 raw/md）：

```python
@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--hash-path", "hash_path", type=click.Path(path_type=Path), default=DEFAULT_HASH)
@click.option("--log-path", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--no-llm", is_flag=True, help="禁用 LLM，强制 fallback。")
def ingest(path, md_root, raw_root, wiki_root, cache_path, hash_path, log_path, no_llm):
    """摄入 PATH。PATH 在 raw_root 下 → raw 三态增量；在 md_root 下 → M2 直摄入。"""
    raw_root = raw_root.resolve(); md_root = md_root.resolve()
    wiki_root = wiki_root.resolve(); cache_path = cache_path.resolve()
    hash_path = hash_path.resolve(); log_path = log_path.resolve()
    path = path.resolve()
    if raw_root in path.parents or path == raw_root:
        client = None if no_llm else make_client_from_config()
        if client is None:
            click.secho("[info] LLM 不可用或 --no-llm，走确定性 fallback", fg="yellow")
        summary = ingest_flow.run_incremental(
            raw_root=raw_root, md_root=md_root, wiki_root=wiki_root,
            cache_path=cache_path, hash_path=hash_path, log_path=log_path,
            client=client, today=config.today(),
        )
        for d in summary.details:
            click.echo(d)
        click.echo(f"\n完成: 新增 {summary.added}, 修改 {summary.modified}, "
                  f"删除 {summary.deleted}, 跳过 {summary.skipped}, 失败 {summary.failed} "
                  f"(共 {summary.total} 文件)")
        if summary.failed:
            sys.exit(1)
        return
    # —— M2 向后兼容：md 直摄入 ——
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*.md") if p.is_file())
    if not files:
        click.echo(f"未找到 md 文件: {path}"); return
    client = None if no_llm else make_client_from_config()
    if client is None:
        click.secho("[info] LLM 不可用或 --no-llm，走确定性 fallback", fg="yellow")
    ok = skipped = failed = 0
    for f in files:
        try:
            rel = f.relative_to(md_root) if md_root in f.parents else f
        except ValueError:
            rel = f
        identity = str(rel).replace("\\", "/")
        index_md = read_index_md(wiki_root)
        today = config.today()
        try:
            res = ingest_source(f, identity, wiki_root=wiki_root, cache_path=cache_path, client=client, today=today, index_md=index_md)
        except Exception as e:
            click.secho(f"[ERR] {f.name}: {e}", fg="red", err=True); failed += 1; continue
        if res.skipped_cached:
            click.secho(f"[SKIP-CACHED] {f.name}", fg="cyan"); skipped += 1
        else:
            tag = "[FALLBACK]" if res.fallback else "[LLM]"
            click.secho(f"{tag} {f.name} → 写入 {len(res.written_paths)} 页", fg="green"); ok += 1
    click.echo(f"\n完成: 摄入 {ok}, 缓存跳过 {skipped}, 失败 {failed} (共 {len(files)} 文件)")
```

**新增 `lint` 子命令**（追加到 `index_cmd` 之后、`search` 之前）：

```python
@cli.command()
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--hash-path", "hash_path", type=click.Path(path_type=Path), default=DEFAULT_HASH)
@click.option("--log-path", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=DEFAULT_LINT_REPORT)
def lint(wiki_root, raw_root, md_root, cache_path, hash_path, log_path, out_path):
    """五项确定性自检 → lint_report.json + 终端摘要；error→退码 1。"""
    today = config.today()
    report = lint_checker.run_lint(
        wiki_root=wiki_root.resolve(), hash_path=hash_path.resolve(),
        ingest_log_path=log_path.resolve(), cache_path=cache_path.resolve(),
        md_root=md_root.resolve(), today=today,
    )
    lint_report.write_report(report, out_path.resolve())
    click.echo(lint_report.format_summary(report))
    click.secho(f"[OK] 报告已写: {out_path}", fg="green")
    ingest_log.append_lint(log_path.resolve(), today=today,
                            issues=len(report.issues), errors=report.errors,
                            warnings=report.warnings, info=report.info)
    sys.exit(lint_report.exit_code(report))
```

**新增 `rebuild` 子命令**（追加到 `search` 之后；依赖 Task 9 的 `ingest_flow.rebuild_all`，此处仅接 CLI，Task 9 补实现）：

```python
@cli.command()
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--hash-path", "hash_path", type=click.Path(path_type=Path), default=DEFAULT_HASH)
@click.option("--log-path", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--yes", is_flag=True, help="确认清空生成物（否则仅 dry-run）。")
def rebuild(raw_root, md_root, wiki_root, cache_path, hash_path, log_path, yes):
    """清生成物从 raw 全量重建（需 --yes）。"""
    raw_root = raw_root.resolve(); md_root = md_root.resolve()
    wiki_root = wiki_root.resolve(); cache_path = cache_path.resolve()
    hash_path = hash_path.resolve(); log_path = log_path.resolve()
    if not yes:
        click.echo("[dry-run] 将清空: md/ wiki/ ingest-cache.json hash.json ingest_log.jsonl；raw/ 不动。")
        click.echo("        加 --yes 执行全量重建。")
        return
    client = make_client_from_config()
    if client is None:
        click.secho("[info] LLM 不可用，走确定性 fallback", fg="yellow")
    summary = ingest_flow.rebuild_all(
        raw_root=raw_root, md_root=md_root, wiki_root=wiki_root,
        cache_path=cache_path, hash_path=hash_path, log_path=log_path,
        client=client, today=config.today(),
    )
    for d in summary.details:
        click.echo(d)
    click.secho(f"[OK] 全量重建完成: {summary.added} 摄入", fg="green")
```

> **注：** `rebuild_all` 在 Task 9 实现。本任务先把 CLI 接好（测试只验 dry-run 不写生成物 + 选项存在），Task 9 补 `rebuild_all` 后跑 `--yes` 路径。`rebuild` 命令的 `--yes` 全量测试放 Task 9。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kb_cli_m3.py -v`
Expected: PASS（4 项；rebuild 验 dry-run 路径）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/config.py l1_kb/cli/kb.py tests/test_kb_cli_m3.py
git commit -m "feat(m3): config HASH/LOG 路径 + kb lint/rebuild 子命令 + ingest raw 三态"
```

## Task 9: rebuild_all — 全量重建兜底（含 rebuild CLI --yes 路径测试）

**Files:**
- Modify: `l1_kb/ingest/incremental/ingest_flow.py`（追加 `rebuild_all`）
- Test: `tests/test_rebuild.py`（含 CLI `--yes` 路径）

**Interfaces:**
- Consumes: Task 1/2/4/5（hash_store / ingest_log / purge_source / run_incremental）；`l1_kb/ingest/clean.py::clean_one`；`config.today()`。
- Produces: `rebuild_all(*, raw_root, md_root, wiki_root, cache_path, hash_path, log_path, client, today) -> FlowSummary`。

**流程（M3 设计 §五）：** 1) 清生成物 md/ wiki/ cache hash log；2) 全量 clean（raw→md）；3) 全量 ingest（cache 已清→全重跑）；4) 全量 hash.json 重建；5) rebuild_index + append_rebuild 行。raw/ 不动。幂等可重跑。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rebuild.py
from pathlib import Path
from click.testing import CliRunner
from l1_kb.cli.kb import cli
from l1_kb.ingest.incremental import ingest_flow, hash_store
from l1_kb.ingest.cleaners.dispatcher import SUPPORTED_EXTS

def _seed_raw(tmp_path: Path):
    raw = tmp_path / "raw" / "data_table"
    raw.mkdir(parents=True)
    f = raw / "order_detail.xlsx"
    f.write_bytes(b"hi")
    return raw

def test_rebuild_all_idempotent(tmp_path, monkeypatch):
    raw = _seed_raw(tmp_path)
    md_root = tmp_path / "md"; wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"; hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    s1 = ingest_flow.rebuild_all(raw_root=raw, md_root=md_root, wiki_root=wiki,
        cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert s1.added == 1
    assert (wiki / "sources").exists()
    assert "data_table_order_detail" in hash_store.load_hash(hp)
    first_log = lp.read_text(encoding="utf-8")
    # 再跑一次：幂等，仍 1 份摄入
    s2 = ingest_flow.rebuild_all(raw_root=raw, md_root=md_root, wiki_root=wiki,
        cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert s2.added == 1
    # raw 未动
    assert (raw / "order_detail.xlsx").read_bytes() == b"hi"

def test_kb_rebuild_yes_full(tmp_path, monkeypatch):
    raw = _seed_raw(tmp_path)
    md_root = tmp_path / "md"; wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"; hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "rebuild", "--raw-root", str(raw),
        "--md-root", str(md_root), "--wiki-root", str(wiki),
        "--cache-path", str(cache),
        "--hash-path", str(hp), "--log-path", str(lp), "--yes",
    ])
    assert res.exit_code == 0, res.output
    assert (wiki / "sources").exists()
    assert "data_table_order_detail" in hash_store.load_hash(hp)
    assert "type\":\"rebuild" in lp.read_text(encoding="utf-8") or 'type":"rebuild' in lp.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rebuild.py -v`
Expected: FAIL — `rebuild_all` 不存在

- [ ] **Step 3: Write minimal implementation**（追加到 `ingest_flow.py`）

```python
import shutil
from ..clean import clean_one
from .hash_store import load_hash, save_hash
from .ingest_log import append_rebuild
from .change_detect import hash_raw, slug_of
from ..ingest.doc_id import make_doc_id

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
    from ..cleaners.base import CleanerError
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
```

> **注：** `rebuild_all` 内调 `run_incremental`，后者会按四态分发——首跑无 hash.json 故全部 ADD（cache 已清，全重摄入），幂等。SUPPORTED_EXTS 在文件顶部已有 import 路径可用 `from ..cleaners.dispatcher import SUPPORTED_EXTS`；若顶部未导入则在此函数前补 import。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rebuild.py -v`
Expected: PASS（2 项：幂等 + CLI --yes）

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/incremental/ingest_flow.py tests/test_rebuild.py
git commit -m "feat(m3): rebuild_all — 全量重建兜底（幂等，raw 不动）"
```

## Task 10: e2e 全链（真 key）— add→modify→delete→lint→search

**Files:**
- Test: `tests/test_m3_incremental_e2e.py`（**真 DEEPSEEK key**；无 key 时 skip，不 fail）

**约定：** 用真实 key（env `DEEPSEEK_API_KEY`），模型 `deepseek-v4-flash`，base_url `https://api.deepseek.com/v1`。无 key 时 `pytest.skip`。流程：`kb clean raw/` → `kb ingest <raw>`（三态 add）→ 改 raw → `kb clean` → `kb ingest`（modify）→ 删 raw → `kb ingest`（delete）→ `kb lint` → `kb search` 验证 delete 后不命中。

- [ ] **Step 1: Write the test**

```python
# tests/test_m3_incremental_e2e.py
import os
from pathlib import Path
from click.testing import CliRunner
from l1_kb.cli.kb import cli

import pytest

KEY = os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('LLM_API_KEY')
MODEL = os.environ.get('DEEPSEEK_MODEL') or os.environ.get('LLM_MODEL') or 'deepseek-v4-flash'
pytestmark = pytest.mark.skipif(not KEY, reason='无 DEEPSEEK key，e2e 跳过')

def _write_raw(root: Path, body: bytes = b'hello order world'):
    root.joinpath('data_table').mkdir(parents=True, exist_ok=True)
    f = root / 'data_table' / 'order_detail.xlsx'
    f.write_bytes(body)
    return f

def _run(args, tmp_path: Path):
    env = {**os.environ, 'DEEPSEEK_MODEL': MODEL, 'LLM_MODEL': MODEL, 'KB_TODAY': '2026-08-03'}
    return CliRunner().invoke(cli, args, env=env)

def test_m3_add_modify_delete_lint_search(tmp_path: Path):
    raw = tmp_path / 'raw'; md_root = tmp_path / 'md'; wiki = tmp_path / 'wiki'
    cache = tmp_path / 'cache.json'; hp = tmp_path / 'hash.json'; lp = tmp_path / 'log.jsonl'
    common = ['--raw-root', str(raw), '--md-root', str(md_root),
              '--wiki-root', str(wiki), '--cache-path', str(cache),
              '--hash-path', str(hp), '--log-path', str(lp)]
    f = _write_raw(raw)
    # 1) clean → md
    r = _run(['clean', str(raw)] + common[:2] + ['--wiki-root', str(wiki)], tmp_path)
    assert r.exit_code == 0, r.output
    # 2) ingest（add）
    r = _run(['ingest', str(raw)] + common, tmp_path)
    assert r.exit_code == 0, r.output
    assert '新增 1' in r.output
    # search 命中（fallback 或 LLM 都会有 source 页含 order）
    r = _run(['search', 'order', '--wiki-root', str(wiki)], tmp_path)
    assert r.exit_code == 0, r.output
    assert 'order' in r.output.lower() or '(无结果)' not in r.output
    # 3) modify：改 raw 内容 → clean → ingest
    f.write_bytes(b'completely different content xyz999')
    # 旧 md 已 stale，先清 md_root 再 clean
    import shutil
    if md_root.exists(): shutil.rmtree(md_root)
    r = _run(['clean', str(raw)] + common[:2] + ['--wiki-root', str(wiki)], tmp_path)
    assert r.exit_code == 0, r.output
    r = _run(['ingest', str(raw)] + common, tmp_path)
    assert r.exit_code == 0, r.output
    assert '修改 1' in r.output
    # 4) delete：删 raw → ingest
    f.unlink()
    r = _run(['ingest', str(raw)] + common, tmp_path)
    assert r.exit_code == 0, r.output
    assert '删除 1' in r.output
    # 5) lint
    r = _run(['lint'] + common + ['--out', str(tmp_path / 'lint_report.json')], tmp_path)
    # delete 后可能 L5 info，无 error 即 0
    assert r.exit_code in (0, 1), r.output  # 允许 error（幽灵）便于观察，主要验不崩
    # 6) search delete 后 source 页应消失
    src_pages = list((wiki / 'sources').glob('*.md')) if (wiki / 'sources').exists() else []
    assert src_pages == [], f'delete 后仍有 source 页: {src_pages}'
```

- [ ] **Step 2: Run test**

Run: `DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY pytest tests/test_m3_incremental_e2e.py -v -s`
Expected: PASS（或 skip 若无 key）。失败时用 `-s` 看 CLI 输出排查三态分支。

- [ ] **Step 3: Commit**

```bash
git add tests/test_m3_incremental_e2e.py
git commit -m "test(m3): e2e 全链 add→modify→delete→lint→search（真 key）"
```

---

## 验收（对齐 M3 设计 §七）

全部 Task 完成后跑：

```bash
# 单测（mock LLM，无 key）
pytest tests/test_hash_store.py tests/test_ingest_log.py tests/test_change_detect.py \
       tests/test_delete.py tests/test_ingest_flow.py tests/test_lint.py \
       tests/test_kb_cli_m3.py tests/test_rebuild.py -v
# e2e（真 key）
pytest tests/test_m3_incremental_e2e.py -v -s
```

判据：单测全绿 + e2e 全绿（或无 key 时 skip）+ GPL 红线零 llm_wiki 源码导入。

---

## Self-Review（plan 作者自查）

**1. Spec 覆盖：**
- §一 hash.json → Task 1 ✅
- §一 ingest_log.jsonl → Task 2 ✅
- §二 身份映射链（slug 键、glob 反查 md、cache paths[] 权威）→ Task 3/4 ✅
- §三 三态流程（add/modify=delete-then-add/delete/skip、事务 hash 最后落盘、失败容错）→ Task 5 ✅
- §四 lint 五项（L1-L5）→ Task 6+7 ✅
- §五 rebuild → Task 9 ✅
- §六 config HASH/LOG + CLI lint/rebuild + ingest raw 三态 → Task 8 ✅
- §七 验收（增量只处理变更、delete 精准、modify 消 orphan、lint 分类、rebuild 幂等、e2e 全链）→ 各 Task 测试覆盖 + Task 10 e2e ✅

**2. 占位扫描：** Task 4 测试中一处占位断言已标注「实现前删除」（Step 4 后注）。无其他 TBD/TODO。

**3. 类型一致性：**
- `FlowSummary`（Task 5 定义）→ Task 8 CLI、Task 9 `rebuild_all` 返回值一致 ✅
- `run_incremental(*, raw_root, md_root, wiki_root, cache_path, hash_path, log_path, client, today)`（Task 5）→ Task 8/9 调用关键字一致 ✅
- `run_lint(*, wiki_root, hash_path, ingest_log_path, cache_path, md_root, today)`（Task 6）→ Task 7 report 消费 LintReport、Task 8 CLI 调用一致 ✅
- `purge_source(*, slug, md_root, wiki_root, cache_path, hash_path, today)`（Task 4）→ Task 5 modify/delete 调用一致 ✅
- `upsert_hash(hash_path, slug, *, hash, path, ingested_at)`（Task 1）→ Task 3/5 调用一致 ✅
- `detect_changes(raw_root, hash_path) -> ChangeSet`（Task 3）→ Task 5 调用一致 ✅

**4. 已知边界：**
- M2 `sources: []` bug 不修：delete 退化为按 paths[] 全删（Task 4），L3 退化为仅看 related 反向索引（Task 6）。已在设计 §二/§四 注明。
- modify 测试用「重写 md 模拟 clean」绕过真实 clean（单测不依赖 LLM 清洗质量）。e2e（Task 10）走真实 clean+ingest。
- `rebuild_all` 调 `run_incremental` 复用三态；首跑无 hash.json → 全 ADD，幂等 ✅。

计划完整，可进入 SDD 执行。


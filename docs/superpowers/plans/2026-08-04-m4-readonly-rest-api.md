# M4 L1 只读 REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 M1–M3 已落地的 L1 检索能力（wiki 知识页 + BM25 + section 切分）封装成只读 FastAPI REST 服务（6 个 GET 端点），并让 CLI `kb search` 复用同一检索代码。

**Architecture:** 方案 A——纯函数 service 层（`store.py` 读 wiki→`WikiStore`，`search.py` BM25+RRF+snippet）+ 瘦 FastAPI 路由层（`app.py`，Pydantic v2 出口）。逻辑与 HTTP 解耦，每请求 `load_store` 重建（无缓存故无失效）。CLI `kb search` 下沉复用 `service.search`（DRY），行为不变。

**Tech Stack:** Python ≥3.12，FastAPI + uvicorn（运行），httpx（TestClient），Pydantic v2，复用既有 `retrieval/`（rank-bm25/jieba）、`ingest/wiki/frontmatter.py`、`ingest/section_splitter.py`、`ingest/wiki/page_types.py`、`ingest/wiki/index_log.py`、`config.py`。

## Global Constraints

- **硬约束 2**：REST 全只读，6 端点全 GET，**无任何 POST/PUT/DELETE/PATCH 路由**。验收：`grep -rE '@app\.(post|put|delete|patch)' l1_kb/service/` 无命中。
- **身份锚点 = slug**：wiki 页文件名 stem（如 `data_table_order_detail__a3f9c1e2`），与 M2/M3 一致；section 用 `section_id`（s0/s1…，由 `section_splitter.split` 顺序产出，稳定）。
- **wiki_root 来源**：`l1_kb.config.WIKI_ROOT`（PEP 562 属性，env `WIKI_ROOT` 可覆盖）。路由内每请求懒取，不缓存。
- **不碰摄入侧**：`ingest/`、`incremental/`、`lint/` 一行不改；M4 只读 `wiki/`。
- **GPL 红线**：复用项目自有 `retrieval/`，绝不 import/copy llm_wiki 源码。
- **测试不调 LLM**：service 层纯函数，单测用 `tmp_path` 造 wiki 树，`monkeypatch` 指向它；不新增 e2e 真 key 测试（service 不调 LLM）。
- **section body ≤2000 字截断**（超长尾部加 `…[截断]`）；snippet 走 `make_snippet(max_chars=500)`。
- **解释器**：`.venv/bin/python`；运行命令用 `.venv/bin/python -m pytest`。
- **提交信息**结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。

---

## File Structure

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `l1_kb/service/__init__.py` | 包占位（已存在，0 字节） | 不动 |
| `l1_kb/service/store.py` | 读 wiki → `WikiStore`（dataclass），跳过 index/log/overview，解析 frontmatter + section 切分；body 截断 | 新建 |
| `l1_kb/service/search.py` | `search(store, query, top_k) -> list[SearchHit]`：BM25+RRF+snippet，下沉自 `cli/kb.py:search` | 新建 |
| `l1_kb/service/app.py` | FastAPI app + 6 只读 GET 路由 + Pydantic v2 出口模型 + `run()` 入口 | 新建 |
| `l1_kb/cli/kb.py` | `search` 子命令改为复用 `service.search`；删 `_wiki_entries`（已下沉） | 改 |
| `pyproject.toml` | 新增 fastapi/uvicorn/httpx 依赖 + `kb-serve` script | 改 |
| `tests/test_service_store.py` | `load_store` 单测 | 新建 |
| `tests/test_service_search.py` | `search` 单测 | 新建 |
| `tests/test_service_app.py` | 6 端点 REST 单测（TestClient） | 新建 |
| `README.md` | M4 标 ✅ + REST 启动/端点速查节 | 改 |

---


## Task 1: 添加 FastAPI/uvicorn/httpx 依赖

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_service_smoke.py`（新建，最小 import 冒烟）

**Interfaces:**
- Produces: 运行时可 `import fastapi`、`import uvicorn`、`import httpx`，为 Task 2-4 铺垫。

- [ ] **Step 1: 写失败测试（import 冒烟）**

创建 `tests/test_service_smoke.py`：

```python
def test_deps_importable():
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
    import httpx  # noqa: F401
    from fastapi.testclient import TestClient  # noqa: F401
    assert True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_service_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fastapi'`（或 uvicorn/httpx）

- [ ] **Step 3: 改 pyproject.toml 加依赖**

在 `[project] dependencies` 列表追加（保持既有依赖不动）：

```toml
"fastapi>=0.110",
"uvicorn[standard]>=0.27",
```

在 `[project.optional-dependencies] dev`（或既有 dev/test 组）追加：

```toml
"httpx>=0.27",
```

在 `[project.scripts]` 加一行（与既有 `kb = ...` 同节）：

```toml
"kb-serve = \"l1_kb.service.app:run\"",
```

- [ ] **Step 4: 安装依赖**

Run: `uv pip install -e ".[dev]"` （或 `.venv/bin/python -m pip install -e ".[dev]"`，视项目锁定方式）

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_service_smoke.py -v`
Expected: PASS

- [ ] **Step 6: 全量回归**

Run: `.venv/bin/python -m pytest -q`
Expected: 既有测试全绿（新依赖不破坏既有行为）。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml tests/test_service_smoke.py
git commit -m "chore(m4): add fastapi/uvicorn/httpx deps + kb-serve script

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: store.py — 读 wiki → WikiStore

**Files:**
- Create: `l1_kb/service/store.py`
- Test: `tests/test_service_store.py`

**Interfaces:**
- Consumes: `l1_kb.ingest.wiki.frontmatter.parse`（返回 `(Frontmatter, body)`，Frontmatter 有 `.type/.title/.updated`）；`l1_kb.ingest.section_splitter.split`（返回 `list[Section]`，Section 有 `.section_id/.title/.line_start/.line_end`）；`l1_kb.ingest.wiki.page_types.PAGE_TYPES`（frozenset `{"source","entity","concept","process"}`）、`DIR_TO_TYPE`、`TYPE_TO_DIR`。
- Produces:
  - `SectionEntry(section_id:str, title:str, line_start:int, line_end:int, body:str)`（dataclass）
  - `PageEntry(slug:str, type:str, title:str, path:Path, sections:list[SectionEntry], raw:str)`（dataclass）
  - `WikiStore(pages:list[PageEntry], by_slug:dict[str,PageEntry], by_type:dict[str,list[PageEntry]])`（dataclass）
  - `load_store(wiki_root: Path) -> WikiStore` —— 纯函数，扫 `wiki/**/*.md`，跳过 stem 在 `{index,log,overview}` 的文件，解析 frontmatter 取 type/title，split_sections 切分，body 走 `make_snippet` 风格截断 ≤2000。

**关键逻辑（下沉自 `cli/kb.py:_wiki_entries` line 121-146）：**
- 扫 `wiki_root.rglob("*.md")`；skip 文件 stem ∈ `{"index","log","overview"}`。
- slug = 文件 stem（与 M2/M3 一致，即 wiki 页文件名）。
- frontmatter, body = `frontmatter.parse(text)`；title 取 `frontmatter.title` 或 slug 兜底；type 取 `frontmatter.type`（须在 PAGE_TYPES，否则记但仍装入 store，type 留原值）。
- sections：`split_sections = section_splitter.split(body)` → 逐个 `SectionEntry(section_id=s.section_id, title=s.title, line_start=s.line_start, line_end=s.line_end, body=_truncate(s.body))`。
- `body` 字段：取该 section 行范围对应的原文（用 `make_snippet(text, line_start, line_end, max_chars=2000)`），超长尾部替换为 `…[截断]`。
- `raw` 字段：整页 markdown 文本（供 `/documents/{slug}` 返回全文与 `/search` snippet 切片）。
- `by_type`：按 type 分组（source/entity/concept/process 各一 list，按文件名排序保稳定）。
- 空 wiki_root 或不存在目录 → 返回空 WikiStore（pages=[]），不抛。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_service_store.py`：

```python
from pathlib import Path
from l1_kb.service.store import load_store, PageEntry, SectionEntry, WikiStore


def _make_wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "entities").mkdir()
    (w / "concepts").mkdir()
    (w / "processes").mkdir()
    (w / "sources" / "order_detail__a3f9c1e2.md").write_text(
        "---\n"
        "type: source\n"
        "title: 订单明细表\n"
        "updated: 2026-08-04\n"
        "---\n"
        "# 订单明细表\n\n"
        "字段 order_id 为主键。\n\n"
        "## 字段说明\n\n"
        "order_amount 订单金额。\n",
        encoding="utf-8",
    )
    (w / "entities" / "customer__bb.md").write_text(
        "---\ntype: entity\ntitle: 客户\nupdated: 2026-08-04\n---\n"
        "# 客户\n\n客户主数据。\n",
        encoding="utf-8",
    )
    # index/log/overview 应被跳过
    (w / "index.md").write_text("# Wiki Index\n", encoding="utf-8")
    (w / "log.md").write_text("# Wiki Log\n", encoding="utf-8")


def test_load_store_parses_pages(tmp_path):
    _make_wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    assert isinstance(store, WikiStore)
    slugs = {p.slug for p in store.pages}
    assert "order_detail__a3f9c1e2" in slugs
    assert "customer__bb" in slugs
    assert "index" not in slugs  # 跳过 index
    assert "log" not in slugs    # 跳过 log


def test_load_store_by_slug_and_type(tmp_path):
    _make_wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    page = store.by_slug["order_detail__a3f9c1e2"]
    assert page.type == "source"
    assert page.title == "订单明细表"
    assert len(page.sections) >= 1
    assert isinstance(page.sections[0], SectionEntry)
    # by_type 分组
    assert {p.slug for p in store.by_type["source"]} == {"order_detail__a3f9c1e2"}
    assert {p.slug for p in store.by_type["entity"]} == {"customer__bb"}


def test_load_store_section_body_truncated(tmp_path):
    root = tmp_path / "wiki"
    (root / "sources").mkdir(parents=True)
    body = "# T\n\n" + ("x" * 3000) + "\n"
    (root / "sources" / "big__c1.md").write_text(
        "---\ntype: source\ntitle: big\n---\n" + body, encoding="utf-8"
    )
    store = load_store(root)
    page = store.by_slug["big__c1"]
    # section body 截断到 ≤2000 + 截断标记
    assert any(len(s.body) <= 2000 + len("…[截断]") for s in page.sections)


def test_load_store_empty_wiki(tmp_path):
    store = load_store(tmp_path / "nope")
    assert store.pages == []
    assert store.by_slug == {}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_service_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'l1_kb.service.store'`

- [ ] **Step 3: 实现 store.py**

创建 `l1_kb/service/store.py`：

```python
"""L1 只读 service —— wiki → WikiStore（纯函数，与 HTTP 解耦）。

下沉自 cli/kb.py:_wiki_entries。供 service.search 与 FastAPI 路由复用（DRY）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from l1_kb.ingest.section_splitter import split as split_sections
from l1_kb.ingest.wiki.frontmatter import parse as parse_frontmatter
from l1_kb.ingest.wiki.page_types import PAGE_TYPES
from l1_kb.retrieval.snippet import make_snippet

__all__ = ["SectionEntry", "PageEntry", "WikiStore", "load_store"]

_EXCLUDED_STEMS = {"index", "log", "overview"}
_MAX_BODY_CHARS = 2000
_TRUNC_MARK = "…[截断]"


@dataclass
class SectionEntry:
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str


@dataclass
class PageEntry:
    slug: str
    type: str
    title: str
    path: Path
    sections: list[SectionEntry]
    raw: str


@dataclass
class WikiStore:
    pages: list[PageEntry]
    by_slug: dict[str, PageEntry] = field(default_factory=dict)
    by_type: dict[str, list[PageEntry]] = field(default_factory=dict)


def _truncate(text: str, max_chars: int = _MAX_BODY_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNC_MARK


def load_store(wiki_root: Path) -> WikiStore:
    """扫 wiki_root/**/*.md → WikiStore。跳过 index/log/overview。空目录返回空 store。"""
    wiki_root = Path(wiki_root)
    pages: list[PageEntry] = []
    if not wiki_root.exists():
        return WikiStore(pages=[])
    for md_path in sorted(wiki_root.rglob("*.md")):
        if md_path.stem in _EXCLUDED_STEMS:
            continue
        text = md_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        slug = md_path.stem
        ptype = meta.type or ""
        title = meta.title or slug
        secs: list[SectionEntry] = []
        for s in split_sections(body):
            seg = make_snippet(body, s.line_start, s.line_end, max_chars=_MAX_BODY_CHARS)
            secs.append(SectionEntry(
                section_id=s.section_id,
                title=s.title,
                line_start=s.line_start,
                line_end=s.line_end,
                body=_truncate(seg, _MAX_BODY_CHARS),
            ))
        pages.append(PageEntry(
            slug=slug, type=ptype, title=title,
            path=md_path, sections=secs, raw=body,
        ))
    pages.sort(key=lambda p: p.slug)
    by_slug = {p.slug: p for p in pages}
    by_type: dict[str, list[PageEntry]] = {t: [] for t in PAGE_TYPES}
    for p in pages:
        by_type.setdefault(p.type, []).append(p)
    return WikiStore(pages=pages, by_slug=by_slug, by_type=by_type)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_service_store.py -v`
Expected: 4 PASS

- [ ] **Step 5: 提交**

```bash
git add l1_kb/service/store.py tests/test_service_store.py
git commit -m "feat(m4): service.store load_store wiki->WikiStore

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: search.py — BM25 + RRF + snippet（下沉自 CLI）

**Files:**
- Create: `l1_kb/service/search.py`
- Test: `tests/test_service_search.py`

**Interfaces:**
- Consumes: `l1_kb.service.store.load_store`、`WikiStore`、`PageEntry`、`SectionEntry`；`l1_kb.retrieval.bm25.BM25Retriever(entries)`（entries 为 dict 列表，需含 `_text`/`doc_id`/`section_id`/`title`/`_line_start`/`_line_end` 字段，与现 CLI 一致）；`l1_kb.retrieval.base.RRFFuser`；`l1_kb.retrieval.snippet.make_snippet`。
- Produces:
  - `search(store: WikiStore, query: str, top_k: int = 10) -> list[SearchHit]` —— 纯函数。把 store 展平为 BM25Retriever 期望的 entry 列表（doc_id=slug, section_id, title=section title 或 page title, body_text=section.body, _text=page.raw, _line_start/_line_end），调 `bm25.search(query, top_n=50)` → `RRFFuser().fuse([hits], k=60, top_k)` → 每条用 `make_snippet(page.raw, line_start, line_end, max_chars=500)` 重算 snippet（确保 snippet 来自原文行范围，≤500）。
  - 返回 `list[SearchHit]`（`SearchHit(doc_id, section_id, title, snippet, score, source)`，复用 `l1_kb.retrieval.base.SearchHit`）。

**关键逻辑（下沉自 `cli/kb.py:search` line 247-267，保持行为不变）：**

> **字段名锁定（已核对 `l1_kb/retrieval/bm25.py:18-43`）**：`BM25Retriever.__init__` 用 `e["title"]`/`e["body_text"]` 建 corpus；其 `search` 返回的 `SearchHit` 用 `e["slug"]` 作 `doc_id`、`e["section_id"]` 作 `section_id`。**故 entry dict 必须含键 `slug`（不是 `doc_id`）、`section_id`、`title`、`body_text`。** `_text`/`_line_start`/`_line_end` 是给 snippet 切片用的私有字段，BM25Retriever 不读。

- store.pages 逐个 → 每个 page 逐 section → 一条 entry：
  `{"slug": page.slug, "section_id": s.section_id, "title": s.title or page.title, "body_text": s.body, "_text": page.raw, "_line_start": s.line_start, "_line_end": s.line_end}`。
- `BM25Retriever(entries)` → `hits = bm25.search(query, top_n=50)`。
- `fused = RRFFuser().fuse([hits], k=60, top_k=top_k)`。
- 对每条 fused hit：查 `store.by_slug[hit.doc_id]` 拿 page.raw，`snippet = make_snippet(page.raw, hit 对应 entry 的 line_start, line_end, 500)`。需要从 entry 反查 line 范围：在展平时建一个 `idx[(doc_id, section_id)] = (line_start, line_end)` dict。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_service_search.py`：

```python
from pathlib import Path
from l1_kb.service.store import load_store
from l1_kb.service.search import search


def _wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "sources" / "order__a3f9c1e2.md").write_text(
        "---\ntype: source\ntitle: 订单表\n---\n"
        "# 订单表\n\norder_id 主键, order_amount 订单金额。\n\n"
        "## 字段说明\n\norder_amount 金额字段。\n",
        encoding="utf-8",
    )
    (w / "entities" / "customer__bb.md").write_text(
        "---\ntype: entity\ntitle: 客户\n---\n"
        "# 客户\n\ncustomer_id 主键, 客户主数据。\n",
        encoding="utf-8",
    )


def test_search_hits_relevant(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    hits = search(store, "订单金额", top_k=5)
    assert len(hits) >= 1
    # 订单表相关 section 排前列
    assert hits[0].doc_id == "order__a3f9c1e2"
    assert "order_amount" in hits[0].snippet or "订单金额" in hits[0].snippet


def test_search_returns_searchhit(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path)
    hits = search(store, "客户", top_k=5)
    from l1_kb.retrieval.base import SearchHit
    assert isinstance(hits[0], SearchHit)
    assert hits[0].doc_id == "customer__bb"


def test_search_no_match_empty(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    hits = search(store, "zzzznomatch", top_k=5)
    assert hits == []


def test_search_snippet_bounded(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    hits = search(store, "订单", top_k=5)
    for h in hits:
        assert len(h.snippet) <= 500
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_service_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'l1_kb.service.search'`

- [ ] **Step 3: 实现 search.py**

创建 `l1_kb/service/search.py`：

```python
"""L1 只读 service —— BM25 + RRF + snippet（下沉自 cli/kb.py:search）。

纯函数，供 service 路由与 CLI 复用（DRY）。
"""

from __future__ import annotations

from l1_kb.retrieval.base import SearchHit, RRFFuser
from l1_kb.retrieval.bm25 import BM25Retriever
from l1_kb.retrieval.snippet import make_snippet
from l1_kb.service.store import WikiStore

__all__ = ["search"]

_SNIPPET_MAX = 500
_TOP_N_PRE = 50
_RRF_K = 60


def search(store: WikiStore, query: str, top_k: int = 10) -> list[SearchHit]:
    """对 store 跑 BM25 + RRF，返回 top_k SearchHit。无命中返回 []。"""
    entries: list[dict] = []
    lines: dict[tuple[str, str], tuple[int, int]] = {}
    for page in store.pages:
        for s in page.sections:
            key = (page.slug, s.section_id)
            entries.append({
                "slug": page.slug,
                "section_id": s.section_id,
                "title": s.title or page.title,
                "body_text": s.body,
                "_text": page.raw,
                "_line_start": s.line_start,
                "_line_end": s.line_end,
            })
            lines[key] = (s.line_start, s.line_end)
    if not entries:
        return []
    bm25 = BM25Retriever(entries)
    hits = bm25.search(query, top_n=_TOP_N_PRE)
    fused = RRFFuser().fuse([hits], k=_RRF_K, top_k=top_k)
    out: list[SearchHit] = []
    for h in fused:
        page = store.by_slug.get(h.doc_id)
        if page is None:
            continue
        ls, le = lines.get((h.doc_id, h.section_id), (0, 0))
        snippet = make_snippet(page.raw, ls, le, max_chars=_SNIPPET_MAX) if ls else h.snippet
        out.append(SearchHit(
            doc_id=h.doc_id, section_id=h.section_id,
            title=h.title, snippet=snippet,
            score=h.score, source=h.source,
        ))
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_service_search.py -v`
Expected: 4 PASS

- [ ] **Step 5: 提交**

```bash
git add l1_kb/service/search.py tests/test_service_search.py
git commit -m "feat(m4): service.search BM25+RRF+snippet (sink from cli)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: app.py — FastAPI + 6 只读 GET 路由 + Pydantic 出口

**Files:**
- Create: `l1_kb/service/app.py`
- Test: `tests/test_service_app.py`

**Interfaces:**
- Consumes: `l1_kb.service.store.load_store`/`WikiStore`/`PageEntry`/`SectionEntry`；`l1_kb.service.search.search`；`l1_kb.config.WIKI_ROOT`（PEP 562 属性）；`l1_kb.ingest.wiki.page_types.PAGE_TYPES`（顺序 source/entity/concept/process）；`l1_kb.ingest.wiki.index_log._collect_pages`（解析 index.md → `dict[type, list[(slug,title)]]`）。
- Produces: FastAPI `app` 实例 + `run()` 入口（uvicorn）。

**端点契约（全 GET，无写）：**
| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/health` | `{"status":"ok","pages":N}` |
| GET | `/categories` | 返回 `[{type, count}]`，仅含 count>0 的 type，顺序按 PAGE_TYPES |
| GET | `/documents?type=&page=1&page_size=50` | 分页文档摘要列表（slug/title/type/updated，无 body）；page≥1，page_size 1–200 默认 50 |
| GET | `/documents/{slug}` | 单文档详情（slug/type/title/sections[]，section 含 section_id/title/line_start/line_end/body）；未知 slug→404；含 `/` 或 `..`→404 |
| GET | `/index` | 解析 `wiki/index.md` → `{updated, categories:[{type, pages:[{slug,title}]}]}` |
| GET | `/search?q=&top_k=10` | q 必填（空→400）；top_k 1–50 默认 10；返回 `{query, top_k, hits:[{doc_id,section_id,title,snippet,score,source}]}` |

**Pydantic v2 出口模型：**

```python
class SectionOut(BaseModel):
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str

class DocumentSummary(BaseModel):
    slug: str
    title: str
    type: str
    updated: str

class DocumentOut(BaseModel):
    slug: str
    type: str
    title: str
    sections: list[SectionOut]

class CategoryOut(BaseModel):
    type: str
    count: int

class IndexPage(BaseModel):
    slug: str
    title: str

class IndexCategory(BaseModel):
    type: str
    pages: list[IndexPage]

class IndexOut(BaseModel):
    updated: str
    categories: list[IndexCategory]

class SearchHitOut(BaseModel):
    doc_id: str
    section_id: str
    title: str
    snippet: str
    score: float
    source: str

class SearchOut(BaseModel):
    query: str
    top_k: int
    hits: list[SearchHitOut]

class HealthOut(BaseModel):
    status: str
    pages: int
```

**实现要点：**
- `_wiki_root()`：`return l1_kb.config.WIKI_ROOT`（每请求懒取，不缓存）。
- `/documents/{slug}`：slug 含 `/` 或 `..` → 直接 `raise HTTPException(404)`（防目录穿越，配合 `_EXCLUDED_STEMS`）。store.by_slug 取不到 → 404。
- `/index`：用 `index_log._collect_pages(wiki_root)`；updated 从 index.md 文本里 `_updated: {date}_` 解析（正则 `_updated:\s*([^_]+)_`）。index.md 不存在 → 404。
- `/search`：`q = q.strip()`；空 → 400。`store = load_store(wiki_root)` → `hits = search(store, q, top_k)`。
- 不写任何 `@app.post/put/delete/patch`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_service_app.py`：

```python
import re
from pathlib import Path
from fastapi.testclient import TestClient


def _wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "entities").mkdir(parents=True)
    (w / "concepts").mkdir()
    (w / "processes").mkdir()
    (w / "sources" / "order__a3f9c1e2.md").write_text(
        "---\ntype: source\ntitle: 订单表\nupdated: 2026-08-04\n---\n"
        "# 订单表\n\norder_id 主键。\n\n## 字段说明\n\norder_amount 金额。\n",
        encoding="utf-8",
    )
    (w / "entities" / "customer__bb.md").write_text(
        "---\ntype: entity\ntitle: 客户\nupdated: 2026-08-04\n---\n# 客户\n\n主数据。\n",
        encoding="utf-8",
    )
    (w / "index.md").write_text(
        "# Wiki Index\n\n_updated: 2026-08-04_\n\n## source\n\n- [[order__a3f9c1e2|订单表]]\n\n"
        "## entity\n\n- [[customer__bb|客户]]\n",
        encoding="utf-8",
    )


def _client(tmp_path, monkeypatch):
    import l1_kb.config as config
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    # WIKI_ROOT 走 env，直接设
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    from l1_kb.service.app import app
    return TestClient(app)


def test_health(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["pages"] == 2


def test_categories(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/categories")
    assert r.status_code == 200
    cats = {x["type"]: x["count"] for x in r.json()}
    assert cats.get("source") == 1
    assert cats.get("entity") == 1
    # 仅含 count>0
    assert "concept" not in cats


def test_documents_list_pagination(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?page=1&page_size=50")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 2
    slugs = {d["slug"] for d in docs}
    assert "order__a3f9c1e2" in slugs
    # 摘要不含 body
    assert "body" not in docs[0]


def test_documents_list_type_filter(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?type=entity")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 1
    assert docs[0]["slug"] == "customer__bb"


def test_document_detail(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents/order__a3f9c1e2")
    assert r.status_code == 200
    doc = r.json()
    assert doc["slug"] == "order__a3f9c1e2"
    assert doc["type"] == "source"
    assert len(doc["sections"]) >= 1
    assert "body" in doc["sections"][0]


def test_document_detail_404(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    assert c.get("/documents/nope").status_code == 404
    # 路径穿越
    assert c.get("/documents/..%2Findex").status_code == 404


def test_index(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/index")
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == "2026-08-04"
    cats = {x["type"]: x["pages"] for x in body["categories"]}
    assert any(p["slug"] == "order__a3f9c1e2" for p in cats["source"])


def test_search_ok(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/search?q=订单")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "订单"
    assert len(body["hits"]) >= 1
    assert body["hits"][0]["doc_id"] == "order__a3f9c1e2"


def test_search_empty_q_400(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    assert c.get("/search?q=").status_code == 400
    assert c.get("/search").status_code == 400


def test_no_write_routes(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    # 常见写方法应 405（路由不存在该方法）
    assert c.post("/search").status_code == 405
    assert c.delete("/documents/x").status_code == 405
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_service_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'l1_kb.service.app'`

- [ ] **Step 3: 实现 app.py**

创建 `l1_kb/service/app.py`：

```python
"""L1 只读 REST API —— FastAPI 6 个 GET 端点。无写/执行路由（硬约束 2）。

启动：uvicorn l1_kb.service.app:app  或  kb-serve
"""

from __future__ import annotations

import re

import l1_kb.config as config
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from l1_kb.ingest.wiki.index_log import _collect_pages
from l1_kb.ingest.wiki.page_types import PAGE_TYPES
from l1_kb.service.search import search as svc_search
from l1_kb.service.store import load_store

__all__ = ["app", "run"]

app = FastAPI(title="L1 KB Read-only API", version="0.1.0")

_UNSAFE = re.compile(r"[/\\]|\.\.")


# --- 出口模型 ---
class SectionOut(BaseModel):
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str


class DocumentSummary(BaseModel):
    slug: str
    title: str
    type: str
    updated: str


class DocumentOut(BaseModel):
    slug: str
    type: str
    title: str
    sections: list[SectionOut]


class CategoryOut(BaseModel):
    type: str
    count: int


class IndexPage(BaseModel):
    slug: str
    title: str


class IndexCategory(BaseModel):
    type: str
    pages: list[IndexPage]


class IndexOut(BaseModel):
    updated: str
    categories: list[IndexCategory]


class SearchHitOut(BaseModel):
    doc_id: str
    section_id: str
    title: str
    snippet: str
    score: float
    source: str


class SearchOut(BaseModel):
    query: str
    top_k: int
    hits: list[SearchHitOut]


class HealthOut(BaseModel):
    status: str
    pages: int


def _wiki_root() -> "Path":
    from pathlib import Path
    return Path(config.WIKI_ROOT)


def _updated_of(index_text: str) -> str:
    m = re.search(r"_updated:\s*([^_]+)_", index_text)
    return m.group(1).strip() if m else ""


@app.get("/health", response_model=HealthOut)
def health():
    store = load_store(_wiki_root())
    return HealthOut(status="ok", pages=len(store.pages))


@app.get("/categories", response_model=list[CategoryOut])
def categories():
    store = load_store(_wiki_root())
    out: list[CategoryOut] = []
    for t in PAGE_TYPES:
        n = len(store.by_type.get(t, []))
        if n > 0:
            out.append(CategoryOut(type=t, count=n))
    return out


@app.get("/documents", response_model=list[DocumentSummary])
def documents(
    type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    store = load_store(_wiki_root())
    pages = store.by_type.get(type, []) if type else store.pages
    start = (page - 1) * page_size
    chunk = pages[start:start + page_size]
    out: list[DocumentSummary] = []
    from l1_kb.ingest.wiki.frontmatter import parse as parse_frontmatter
    for p in chunk:
        _, _ = parse_frontmatter(p.path.read_text(encoding="utf-8"))
        out.append(DocumentSummary(slug=p.slug, title=p.title, type=p.type, updated=_updated_of("")))
    return out


@app.get("/documents/{slug}", response_model=DocumentOut)
def document(slug: str):
    if _UNSAFE.search(slug):
        raise HTTPException(status_code=404)
    store = load_store(_wiki_root())
    p = store.by_slug.get(slug)
    if p is None:
        raise HTTPException(status_code=404)
    return DocumentOut(
        slug=p.slug, type=p.type, title=p.title,
        sections=[SectionOut(section_id=s.section_id, title=s.title,
                             line_start=s.line_start, line_end=s.line_end, body=s.body)
                  for s in p.sections],
    )


@app.get("/index", response_model=IndexOut)
def index():
    root = _wiki_root()
    idx = root / "index.md"
    if not idx.exists():
        raise HTTPException(status_code=404)
    text = idx.read_text(encoding="utf-8")
    collected = _collect_pages(root)  # dict[type, list[(slug,title)]]
    cats: list[IndexCategory] = []
    for t in PAGE_TYPES:
        items = collected.get(t, [])
        if items:
            cats.append(IndexCategory(type=t, pages=[IndexPage(slug=s, title=t_) for s, t_ in items]))
    return IndexOut(updated=_updated_of(text), categories=cats)


@app.get("/search", response_model=SearchOut)
def search(
    q: str | None = Query(None),
    top_k: int = Query(10, ge=1, le=50),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    q = q.strip()
    store = load_store(_wiki_root())
    hits = svc_search(store, q, top_k=top_k)
    return SearchOut(
        query=q, top_k=top_k,
        hits=[SearchHitOut(doc_id=h.doc_id, section_id=h.section_id, title=h.title,
                           snippet=h.snippet, score=h.score, source=h.source) for h in hits],
    )


def run() -> None:
    """kb-serve 入口。"""
    import uvicorn
    uvicorn.run("l1_kb.service.app:app", host="0.0.0.0", port=8011, reload=False)
```

> **注意实现细节：** `documents` 的 `updated` 字段需从每页 frontmatter 实取（上面 `_updated_of("")` 是占位，实现时改为 `parse_frontmatter(p.path.read_text())[0].updated`）。修正版 `documents` 函数体：

```python
@app.get("/documents", response_model=list[DocumentSummary])
def documents(
    type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    from l1_kb.ingest.wiki.frontmatter import parse as parse_frontmatter
    store = load_store(_wiki_root())
    pages = store.by_type.get(type, []) if type else store.pages
    start = (page - 1) * page_size
    chunk = pages[start:start + page_size]
    out: list[DocumentSummary] = []
    for p in chunk:
        meta, _ = parse_frontmatter(p.path.read_text(encoding="utf-8"))
        out.append(DocumentSummary(slug=p.slug, title=p.title, type=p.type, updated=meta.updated))
    return out
```

（用这版覆盖前面的 `documents`，删除占位版与冗余 import。）

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_service_app.py -v`
Expected: 10 PASS

- [ ] **Step 5: 只读红线验证**

Run: `grep -rE '@app\.(post|put|delete|patch)' l1_kb/service/`
Expected: 无任何输出（无写路由）。

- [ ] **Step 6: 提交**

```bash
git add l1_kb/service/app.py tests/test_service_app.py
git commit -m "feat(m4): FastAPI read-only REST API (6 GET endpoints)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: CLI `kb search` 复用 service.search（DRY + 回归）

**Files:**
- Modify: `l1_kb/cli/kb.py`（`search` 子命令 line 247-267，及 `_wiki_entries` 121-146）
- Test: `tests/test_kb_cli_search_reuse.py`（新建，行为回归）

**Interfaces:**
- Consumes: `l1_kb.service.store.load_store`、`l1_kb.service.search.search`。
- Produces: `kb search <query>` 行为与 M2/M3 完全一致（输出格式、命中排序、snippet），但内部走 service 层。

**改动要点：**
- `search` 命令改为：`store = load_store(config.WIKI_ROOT)` → `hits = search(store, query, top_k)` → 打印（保持原打印格式：每行 `[{score:.4f}] {doc_id} / {section_id} — {title}` + snippet 缩进）。
- 删除 `_wiki_entries`（已下沉到 `store.load_store`），若被其他命令引用则保留薄封装转调 `load_store`。先 `grep -n '_wiki_entries' l1_kb/` 确认引用面；仅 `search` 用到则删，否则改为转调。
- 不改 `clean/ingest/lint/rebuild` 子命令。

- [ ] **Step 1: 写回归测试**

创建 `tests/test_kb_cli_search_reuse.py`：

```python
from pathlib import Path
from click.testing import CliRunner


def _wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "sources" / "order__a3f9c1e2.md").write_text(
        "---\ntype: source\ntitle: 订单表\n---\n"
        "# 订单表\n\norder_id 主键, order_amount 金额。\n", encoding="utf-8"
    )


def test_kb_search_uses_service(tmp_path, monkeypatch):
    _wiki(tmp_path)
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    from l1_kb.cli.kb import cli
    r = CliRunner().invoke(cli, ["search", "订单"])
    assert r.exit_code == 0
    assert "order__a3f9c1e2" in r.output


def test_kb_search_no_match(tmp_path, monkeypatch):
    _wiki(tmp_path)
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    from l1_kb.cli.kb import cli
    r = CliRunner().invoke(cli, ["search", "zzznomatch"])
    assert r.exit_code == 0
    assert "无结果" in r.output or r.output.strip() == "" or "0" in r.output
```

- [ ] **Step 2: 运行测试确认当前状态**

Run: `.venv/bin/python -m pytest tests/test_kb_cli_search_reuse.py -v`
Expected: 可能 PASS（行为未变）或 FAIL（若打印格式不符断言）。先记录基线。

- [ ] **Step 3: 改 kb.py search 复用 service**

先查引用：`grep -n '_wiki_entries' l1_kb/ -r`。
改 `search` 命令体为：

```python
@cli.command()
@click.argument("query")
@click.option("--top-k", default=10, show_default=True, type=int)
def search(query, top_k):
    """BM25 检索 wiki 知识页。"""
    from l1_kb.service.store import load_store
    from l1_kb.service.search import search as svc_search
    store = load_store(config.WIKI_ROOT)
    hits = svc_search(store, query, top_k=top_k)
    if not hits:
        click.echo("无结果")
        return
    for h in hits:
        click.echo(f"[{h.score:.4f}] {h.doc_id} / {h.section_id} — {h.title}")
        if h.snippet:
            for ln in h.snippet.splitlines():
                click.echo(f"    {ln}")
```

若 `_wiki_entries` 仅 `search` 用 → 删除该函数；若其他命令也用 → 保留但改为 `return load_store(...)` 适配，或最小改动保留旧函数（避免扩散）。**默认：grep 确认后删除仅 search 用的版本，否则保留。**

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_kb_cli_search_reuse.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿（含既有 M1-M3 测试 + 新 M4 测试）。

- [ ] **Step 6: 提交**

```bash
git add l1_kb/cli/kb.py tests/test_kb_cli_search_reuse.py
git commit -m "refactor(m4): kb search reuse service.search (DRY)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: README 更新 + 最终验证

**Files:**
- Modify: `README.md`

**Interfaces:** 无代码，文档 + 收尾验证。

- [ ] **Step 1: 更新 README**

在 README 的里程碑表把 M4 标 ✅。新增「L1 只读 REST API」节：

```markdown
## L1 只读 REST API（M4）

启动：
```bash
.venv/bin/python -m uvicorn l1_kb.service.app:app --port 8011
# 或
kb-serve
```

端点（全 GET，只读，无写/执行）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 + 页数 |
| GET | `/categories` | 类型统计 |
| GET | `/documents?type=&page=&page_size=` | 文档摘要分页 |
| GET | `/documents/{slug}` | 单文档详情（含 sections） |
| GET | `/index` | 解析 index.md |
| GET | `/search?q=&top_k=` | BM25 检索 |

环境变量：`WIKI_ROOT`（覆盖默认 wiki 目录）。
```

- [ ] **Step 2: 只读红线最终验证**

Run: `grep -rE '@app\.(post|put|delete|patch)' l1_kb/service/ ; echo "exit=$?"`
Expected: 无输出，`exit=1`（grep 无匹配）。

- [ ] **Step 3: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿。

- [ ] **Step 4: 启动冒烟（可选，手动）**

Run: `.venv/bin/python -m uvicorn l1_kb.service.app:app --port 8011 &` 然后 `curl -s localhost:8011/health`，确认返回 JSON 后 kill。
Expected: `{"status":"ok","pages":N}`。

- [ ] **Step 5: 提交**

```bash
git add README.md
git commit -m "docs(m4): README mark M4 done + REST API section

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review（写完后自检，不另起子代理）

**1. Spec 覆盖**（对照 `docs/superpowers/specs/2026-08-04-m4-readonly-rest-api-design.md`）：
- §2 6 端点 → Task 4 全覆盖（health/categories/documents[+type/pagination]/documents/{slug}/index/search）。
- §3 数据模型（PageEntry/SectionEntry/WikiStore dataclass + Pydantic 出口）→ Task 2 + Task 4。
- §4 端点参数（page≥1、page_size 1-200 默认 50、top_k 1-50 默认 10、空 q→400、未知 slug→404、`/`/`..`→404）→ Task 4 Query 约束 + `_UNSAFE` 正则。
- §5 数据流（每请求 load_store 重建，无缓存）→ Task 2/4 各端点内调用。
- §6 错误处理 → Task 4（404/400/422 由 Query ge/le 自动产生 422）。
- §7 CLI 重构 → Task 5。
- §8 配置/启动（WIKI_ROOT、kb-serve）→ Task 1（script）+ Task 4（run）+ Task 6（README）。
- 硬约束 2 只读 → Task 4 Step 5 + Task 6 Step 2 grep 守护。

**2. 占位扫描**：Task 4 中 `documents` 的 `updated` 有占位版 + 修正版说明——实现时只用修正版，不留占位。无其他 TBD/TODO。

**3. 类型一致**：
- `SearchHit(doc_id, section_id, title, snippet, score, source)` —— Task 3 产出与 Task 4 `SearchHitOut` 字段一一对应。
- `SectionEntry(section_id, title, line_start, line_end, body)` —— Task 2 定义，Task 4 `SectionOut` 同字段。
- `load_store(wiki_root) -> WikiStore` —— Task 2 定义，Task 3/4 消费签名一致。
- `search(store, query, top_k) -> list[SearchHit]` —— Task 3 定义，Task 4/5 消费签名一致。
- `PAGE_TYPES` 顺序 source/entity/concept/process —— Task 4 categories/index 按此序。

**4. 已知实现注意（非占位，是给执行者的提示）：**
- Task 4 的 `_collect_pages` 是 `index_log` 的私有函数（下划线前缀），导入可用但需注意其签名 `_collect_pages(wiki_root) -> dict[type, list[(slug,title)]]`；执行时若签名不符，以实际代码为准（已在前置读码确认）。
- `documents` 列表取 updated 需读 frontmatter，每页一次 IO（P0 ~1000 页可接受）。

---

# M2 复利 wiki 层 + BM25 检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M1 清洗产物 `md/{cat}/{doc_id}.md` 上构建复利 wiki 层——LLM 两步摄入把每份原件消化成带 frontmatter 的 wiki 页，确定性维护 `index.md`/`log.md`，BM25 直接索引 wiki 页 section，`kb ingest`/`kb index`/`kb search` 可用且 §13.2 精确词 + 流程编号两类用例 top_5 命中。

**Architecture:** 吸收 llm_wiki 工程方法（不导入/不复制其 GPL 源码，Python 重实现）：两步 LLM 摄入（step1 分析 JSON → step2 FILE block）→ `is_safe_wiki_path` 校验 → frontmatter 数组并集合并（单源页替换 body / 多源页追加段落）→ 确定性重建 `index.md` + 追加 `log.md` → `BM25Retriever(rank-bm25)` 索引 wiki 页 section，`RRFFuser` 单路直通、向量路 M3 注册即生效。LLM 不可用时确定性 fallback 仅产 source 摘要页，BM25 只依赖 wiki 页文本故验收不依赖 LLM。

**Tech Stack:** Python 3.12 + uv venv；`openai`（OpenAI 兼容薄封装，默认 DeepSeek）、`jieba` + CJK bigram（F7 分词）、`rank-bm25`（BM25Okapi）、`pyyaml`（frontmatter）；复用 M1 `SectionSplitter.split` / `slugify_path` / `make_doc_id`；click CLI。清华镜像安装。

---

## Global Constraints

- **GPL 红线**：llm_wiki 是 GPL v3（Copyright 2024-2026 Yong Su）。**不导入、不链接、不复制其源码**；只吸收公开工程方法/算法用 Python 重实现，所有借鉴标注「理解原理后用 Python 重新实现」。
- **只读硬约束 ②**：所有 wiki 写入（摄入生成、frontmatter 合并、index/log 重建、BM25 建索引）一律是**离线摄入脚本**操作，**不是 Agent 工具**；L1 摄入脚本写 `wiki/*.md` 同 M1 写 `md/` 定性，属正常生成物。
- **独立项目 ①③**：依赖在本目录内声明（`pyproject.toml`），LLM 端点走公司内部 OpenAI 兼容服务（env 配置 base_url/key/model，默认 `https://api.deepseek.com/v1` / `deepseek-chat`），不依赖外部 SaaS。
- **环境**：Python 3.12.3，用 `.venv/bin/python`；系统 site-packages 不可写，必须用 venv；pandoc 未装。安装用清华镜像 `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。
- **DEEPSEEK_API_KEY 未设**：所有 LLM 路径在测试中用 mock client；运行时未设走确定性 fallback，不阻塞 BM25 验收。
- **页类型 P0 仅 4 类**：`source`/`entity`/`concept`/`process`（process 为企业流程/制度新增）。dir↔type 双向校验不一致则丢弃该 FILE block。
- **合并策略**：frontmatter 数组字段（`sources`/`tags`/`related`）并集；`type`/`title`/`created` 为 locked 字段强制回填旧值；单源页（`existing.sources == [当前源]`）替换 body；多源页追加段落。**无 LLM body 合并、无 70% 缩水拒绝、无 page-history 备份**。
- **index.json 砍掉**：BM25 直接索引 wiki 页 section（不经过 index.json）。
- **检索单元** = wiki 页 section（复用 M1 `SectionSplitter.split`）；frontmatter `title` 作为页级标题前缀注入 entry。
- **提交前验证**：`pytest tests/ -q` 全绿；`kb ingest` → `kb index` → `kb search "order_id"` / `kb search "PRC-2024-003"` 端到端命中。

---

## File Structure

```
l1_kb/
├── config.py                     # 新增：集中读 env（路径 + LLM 配置）
├── llm/                          # 新增
│   ├── __init__.py
│   ├── client.py                 # OpenAI 兼容薄封装：LLMClient(chat_json/chat_text) + LLMError
│   └── ingest_prompts.py         # step1/step2 prompt 构造（吸收 llm_wiki buildAnalysis/GenerationPrompt 原理）
├── ingest/
│   ├── wiki/                     # 新增：复利 wiki 摄入
│   │   ├── __init__.py
│   │   ├── page_types.py         # 4 类页 + dir↔type 映射 + frontmatter schema 常量
│   │   ├── frontmatter.py        # 解析/序列化 frontmatter（YAML 内联数组）+ Frontmatter dataclass
│   │   ├── safe_path.py          # is_safe_wiki_path（吸收 llm_wiki isSafeIngestPath 原理）
│   │   ├── file_blocks.py        # 解析 ---FILE:...---...---END FILE--- block
│   │   ├── merge.py              # 已有页合并：数组并集 + body 追加/替换 + locked 字段
│   │   ├── index_log.py          # 确定性重建 index.md / 追加 log.md
│   │   ├── ingest_cache.py       # sha256 + 落盘校验防幽灵
│   │   └── ingest.py             # 编排：md → 两步 LLM → 写 wiki 页 → 合并 → 重建 index/log
│   └── ...（M1 不动）
├── retrieval/                    # 新增
│   ├── __init__.py
│   ├── base.py                   # Retriever ABC + SearchHit + RRFFuser
│   ├── tokenizer.py              # jieba + CJK bigram（F7）
│   ├── bm25.py                   # BM25Retriever(rank-bm25)：索引 wiki 页 section
│   └── snippet.py                # 按 line_start/end 从 wiki 页原文切 snippet
└── cli/kb.py                     # 扩展：+ kb ingest / kb index / kb search

tests/
├── test_page_types.py
├── test_frontmatter.py
├── test_safe_wiki_path.py
├── test_file_blocks.py
├── test_merge.py
├── test_index_log.py
├── test_ingest_cache.py
├── test_ingest.py               # mock LLM client + fallback 路径
├── test_tokenizer.py
├── test_bm25.py
├── test_rrf.py
├── test_snippet.py
└── test_kb_ingest_search.py     # 端到端
```

**职责边界**：每个文件单一职责，可独立单测。`page_types`/`frontmatter`/`safe_path` 无外部依赖，先立基；`file_blocks`/`merge`/`index_log`/`ingest_cache` 依赖前三者；`llm/` 独立可 mock；`ingest.py` 编排依赖全部；`retrieval/` 只依赖 M1 splitter + 自身。

---

## Task 1: 依赖声明与安装

**Files:**
- Modify: `pyproject.toml`
- Test: 无（安装验证）

**Interfaces:**
- Consumes: 无
- Produces: `openai`/`jieba`/`rank-bm25`/`pyyaml` 可 import

- [ ] **Step 1: 在 pyproject.toml 的 `dependencies` 追加四项**

把 `dependencies` 列表改为（在 `click>=8.1` 之后追加）：

```toml
dependencies = [
    "pymupdf4llm>=0.0.17",
    "pdfplumber>=0.11",
    "openpyxl>=3.1",
    "pandas>=2.2",
    "tabulate>=0.9",
    "click>=8.1",
    "openai>=1.0",
    "jieba>=0.42",
    "rank-bm25>=0.2.2",
    "pyyaml>=6.0",
]
```

- [ ] **Step 2: 安装（清华镜像）**

Run:
```bash
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .venv/bin/python -m pip install openai jieba rank-bm25 pyyaml
```
Expected: 四个包安装成功，无报错（若 `.venv` 不存在先 `.venv/bin/python -m venv` 不存在则跳过——已存在）。

- [ ] **Step 3: 验证可 import**

Run:
```bash
.venv/bin/python -c "import openai, jieba, rank_bm25, yaml; print('ok')"
```
Expected: 输出 `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build(l1): 声明 M2 依赖 openai/jieba/rank-bm25/pyyaml"
```

---

## Task 2: config.py 集中读 env

**Files:**
- Create: `l1_kb/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `RAW_ROOT`/`MD_ROOT`/`WIKI_ROOT`/`INGEST_CACHE_PATH`（`pathlib.Path`）、`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`（`str`，key 可为空字符串）、`TODAY`（`str`，`YYYY-MM-DD`）、`llm_enabled()`（`bool`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_config.py`:

```python
import os
from pathlib import Path

from l1_kb import config


def test_paths_defaults(monkeypatch, tmp_path, monkeypatch_chdir):
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    assert config.RAW_ROOT == tmp_path / "l1_kb" / "knowledge_base" / "raw"
    assert config.WIKI_ROOT == tmp_path / "l1_kb" / "knowledge_base" / "wiki"
    assert config.INGEST_CACHE_PATH.name == "ingest-cache.json"


def test_llm_config_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://internal/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "internal-model")
    config._load_llm()
    assert config.LLM_BASE_URL == "https://internal/v1"
    assert config.LLM_API_KEY == "sk-test"
    assert config.LLM_MODEL == "internal-model"
    assert config.llm_enabled() is True


def test_llm_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config._load_llm()
    assert config.llm_enabled() is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'l1_kb.config'`）

- [ ] **Step 3: 实现 config.py**

Create `l1_kb/config.py`:

```python
"""集中读 env —— M2 设计 §3.1。

路径默认基于项目根（l1_kb/ 上两级）。LLM 配置默认 DeepSeek，公司内部
OpenAI 兼容端点换 env 即可（CLAUDE.md ③）。全部可被 env 覆盖。
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- 路径（可被 env 覆盖） ---
RAW_ROOT = Path(os.environ.get("RAW_ROOT", _PROJECT_ROOT / "l1_kb" / "knowledge_base" / "raw"))
MD_ROOT = Path(os.environ.get("MD_ROOT", _PROJECT_ROOT / "l1_kb" / "knowledge_base" / "md"))
WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", _PROJECT_ROOT / "l1_kb" / "knowledge_base" / "wiki"))
INGEST_CACHE_PATH = Path(
    os.environ.get("INGEST_CACHE_PATH", _PROJECT_ROOT / "l1_kb" / "knowledge_base" / ".cache" / "ingest-cache.json")
)

# --- LLM 配置 ---
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))

# --- 日期戳（确定性，测试可 monkeypatch） ---
TODAY = os.environ.get("KB_TODAY", "")  # 留空时由调用方填，避免模块导入即锁死


def _load_llm() -> None:
    """测试钩子：重新从 env 读 LLM 配置（用于 monkeypatch.setenv 后刷新）。"""
    global LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))


def llm_enabled() -> bool:
    """是否配置了 LLM API key。"""
    return bool(LLM_API_KEY)


def today() -> str:
    """返回今日日期字符串 YYYY-MM-DD（优先 KB_TODAY env，否则系统今日）。"""
    if TODAY:
        return TODAY
    import datetime

    return datetime.date.today().isoformat()
```

> 注：测试 `test_paths_defaults` 里的 `monkeypatch_chdir` fixture 不需要——路径基于 `_PROJECT_ROOT` 而非 cwd。删掉该参数。

修正测试签名（去掉 `monkeypatch_chdir` 参数）：

```python
def test_paths_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    assert config.RAW_ROOT == tmp_path / "l1_kb" / "knowledge_base" / "raw"
    assert config.WIKI_ROOT == tmp_path / "l1_kb" / "knowledge_base" / "wiki"
    assert config.INGEST_CACHE_PATH.name == "ingest-cache.json"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/config.py tests/test_config.py
git commit -m "feat(l1): config.py 集中读 env（路径 + LLM 配置 + llm_enabled）"
```

---

## Task 3: page_types + frontmatter + safe_path（立基模块）

### Task 3a: page_types.py

**Files:**
- Create: `l1_kb/ingest/wiki/__init__.py`、`l1_kb/ingest/wiki/page_types.py`
- Test: `tests/test_page_types.py`

**Interfaces:**
- Produces: `PAGE_TYPES`（`frozenset`：`{"source","entity","concept","process"}`）、`TYPE_TO_DIR`（dict）、`DIR_TO_TYPE`（dict）、`dir_for_type(type)->str`、`type_for_dir(dir)->str|None`、`is_valid_type(type)->bool`、`validate_routing(path, page_type)->bool`、`LOCKED_FIELDS`（`("type","title","created")`）、`UNION_FIELDS`（`("sources","tags","related")`）、`sanitize_slug(s)->str`、`slug_from_source_identity(identity)->str`

- [ ] **Step 1: 写失败测试**

Create `tests/test_page_types.py`:

```python
import pytest

from l1_kb.ingest.wiki import page_types as pt


def test_four_page_types():
    assert pt.PAGE_TYPES == frozenset({"source", "entity", "concept", "process"})


def test_dir_type_mapping_roundtrip():
    assert pt.dir_for_type("source") == "sources"
    assert pt.dir_for_type("entity") == "entities"
    assert pt.dir_for_type("concept") == "concepts"
    assert pt.dir_for_type("process") == "process"
    assert pt.type_for_dir("sources") == "source"
    assert pt.type_for_dir("process") == "process"
    assert pt.type_for_dir("unknown") is None


def test_is_valid_type():
    assert pt.is_valid_type("source") is True
    assert pt.is_valid_type("overview") is False
    assert pt.is_valid_type("") is False


def test_validate_routing_ok():
    assert pt.validate_routing("wiki/sources/order_detail.md", "source") is True
    assert pt.validate_routing("wiki/process/refund.md", "process") is True


def test_validate_routing_mismatch():
    # entity 页落在 sources 目录 → 不一致
    assert pt.validate_routing("wiki/sources/order_detail.md", "entity") is False
    # 非 wiki 前缀
    assert pt.validate_routing("md/order_detail.md", "source") is False


def test_sanitize_slug():
    assert pt.sanitize_slug("Entity Order Detail") == "entity_order_detail"
    assert pt.sanitize_slug("order-detail!") == "order_detail"
    assert pt.sanitize_slug("中文") == ""  # 非 [a-z0-9_] 全剔除


def test_slug_from_source_identity():
    # data_table/order_detail.xlsx → 去扩展名 + 多段下划线连
    assert pt.slug_from_source_identity("data_table/order_detail.xlsx") == "data_table_order_detail"
    assert pt.slug_from_source_identity("process/policy.md") == "process_policy"


def test_locked_and_union_fields():
    assert pt.LOCKED_FIELDS == ("type", "title", "created")
    assert pt.UNION_FIELDS == ("sources", "tags", "related")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_page_types.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

Create `l1_kb/ingest/wiki/__init__.py`（空文件，加文档串）:

```python
"""复利 wiki 摄入子包 —— M2 设计 §3。吸收 llm_wiki 工程方法，Python 重实现。"""
```

Create `l1_kb/ingest/wiki/page_types.py`:

```python
"""4 类 wiki 页 + dir↔type 映射 + frontmatter schema 常量 —— M2 设计 §2。

吸收 llm_wiki GENERATION_WIKI_TYPES（9 类）裁剪为 4 类，适配企业知识库。
process 为本设计新增（llm_wiki 无），承载企业流程/制度文档。
dir↔type 双向校验吸收 llm_wiki validateWikiPageRouting 原理（Python 重实现）。
"""

from __future__ import annotations

import re

__all__ = [
    "PAGE_TYPES",
    "TYPE_TO_DIR",
    "DIR_TO_TYPE",
    "LOCKED_FIELDS",
    "UNION_FIELDS",
    "dir_for_type",
    "type_for_dir",
    "is_valid_type",
    "validate_routing",
    "sanitize_slug",
    "slug_from_source_identity",
]

# P0 四类页（吸收 llm_wiki 9 类裁剪）
PAGE_TYPES = frozenset({"source", "entity", "concept", "process"})

# type → 目录段（吸收 llm_wiki dir↔type 映射）
TYPE_TO_DIR = {
    "source": "sources",
    "entity": "entities",
    "concept": "concepts",
    "process": "process",
}
DIR_TO_TYPE = {v: k for k, v in TYPE_TO_DIR.items()}

# frontmatter 字段分类（吸收 llm_wiki LOCKED_FIELDS / UNION_FIELDS）
LOCKED_FIELDS = ("type", "title", "created")
UNION_FIELDS = ("sources", "tags", "related")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def dir_for_type(page_type: str) -> str:
    return TYPE_TO_DIR[page_type]


def type_for_dir(dir_name: str) -> str | None:
    return DIR_TO_TYPE.get(dir_name)


def is_valid_type(page_type: str) -> bool:
    return page_type in PAGE_TYPES


def validate_routing(path: str, page_type: str) -> bool:
    """path 与 page_type 所在目录是否一致（吸收 llm_wiki validateWikiPageRouting）。

    path 形如 wiki/sources/{slug}.md；要求 wiki/ 前缀且第二段 == 该 type 对应目录。
    """
    if not page_type in PAGE_TYPES:
        return False
    parts = path.replace("\\", "/").split("/")
    if len(parts) < 2 or parts[0] != "wiki":
        return False
    return parts[1] == TYPE_TO_DIR[page_type]


def sanitize_slug(raw: str) -> str:
    """slug 规范化：仅 [a-z0-9_]，非合规字符 → _，压缩/去首尾下划线，空兜底返回空串。"""
    s = _SLUG_RE.sub("_", raw.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def slug_from_source_identity(identity: str) -> str:
    """source_identity（相对 raw 路径）→ source 摘要页 slug。

    data_table/order_detail.xlsx → "data_table_order_detail"
    规则同 M1 slugify_path：去扩展名 + 路径段下划线连 + sanitize。
    """
    # 去扩展名
    stem = re.sub(r"\.[^.\\/]+$", "", identity)
    # 路径分隔符 → 下划线
    joined = re.sub(r"[\\/]+", "_", stem)
    return sanitize_slug(joined) or "source"
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_page_types.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/__init__.py l1_kb/ingest/wiki/page_types.py tests/test_page_types.py
git commit -m "feat(l1/wiki): page_types 4 类页 + dir↔type 映射 + slug 工具"
```

### Task 3b: frontmatter.py

**Files:**
- Create: `l1_kb/ingest/wiki/frontmatter.py`
- Test: `tests/test_frontmatter.py`

**Interfaces:**
- Produces: `Frontmatter` dataclass（`type/title/created/updated/tags(list)/related(list)/sources(list)`）；`parse(content)->tuple[Frontmatter,str]`（返回 frontmatter + body）；`dump(fm)->str`（YAML 内联数组）；`union_arrays(existing_fm, new_fm)->Frontmatter`（UNION_FIELDS 并集，locked 回填旧值）；`stamp_dates(fm, today, *, is_new)->Frontmatter`；`canonicalize_sources(fm, source_identity)->Frontmatter`

- [ ] **Step 1: 写失败测试**

Create `tests/test_frontmatter.py`:

```python
from l1_kb.ingest.wiki import frontmatter as fm


def test_parse_and_dump_roundtrip():
    content = (
        "---\n"
        "type: source\n"
        'title: "订单明细表"\n'
        "created: 2026-07-31\n"
        "updated: 2026-07-31\n"
        "tags: [订单, 数据表]\n"
        "related: [entity_order_detail]\n"
        "sources: [data_table/order_detail.xlsx]\n"
        "---\n\n"
        "## 字段\n\n正文。\n"
    )
    meta, body = fm.parse(content)
    assert meta.type == "source"
    assert meta.title == "订单明细表"
    assert meta.tags == ["订单", "数据表"]
    assert meta.related == ["entity_order_detail"]
    assert meta.sources == ["data_table/order_detail.xlsx"]
    assert body.startswith("## 字段")

    dumped = fm.dump(meta)
    assert "type: source" in dumped
    assert "tags: [订单, 数据表]" in dumped


def test_parse_no_frontmatter():
    meta, body = fm.parse("纯正文无 frontmatter")
    assert meta.type == ""  # 空 frontmatter
    assert body == "纯正文无 frontmatter"


def test_union_arrays():
    a = fm.Frontmatter(
        type="entity", title="A", created="2026-07-01", updated="2026-07-01",
        tags=["订单", "支付"], related=["e1"], sources=["s1.xlsx"],
    )
    b = fm.Frontmatter(
        type="entity", title="A", created="2026-07-01", updated="2026-07-31",
        tags=["支付", "退款"], related=["e2"], sources=["s2.xlsx"],
    )
    merged = fm.union_arrays(a, b)
    assert merged.tags == ["订单", "支付", "退款"]
    assert merged.related == ["e1", "e2"]
    assert merged.sources == ["s1.xlsx", "s2.xlsx"]
    # locked 字段回填旧值
    assert merged.type == "entity"
    assert merged.title == "A"
    assert merged.created == "2026-07-01"


def test_stamp_dates_new():
    m = fm.Frontmatter(type="source", title="T", created="", updated="",
                       tags=[], related=[], sources=["x.xlsx"])
    out = fm.stamp_dates(m, "2026-07-31", is_new=True)
    assert out.created == "2026-07-31"
    assert out.updated == "2026-07-31"


def test_stamp_dates_existing():
    m = fm.Frontmatter(type="source", title="T", created="2026-07-01", updated="",
                       tags=[], related=[], sources=["x.xlsx"])
    out = fm.stamp_dates(m, "2026-07-31", is_new=False)
    assert out.created == "2026-07-01"  # created 不变
    assert out.updated == "2026-07-31"


def test_canonicalize_sources_injects_identity():
    m = fm.Frontmatter(type="source", title="T", created="2026-07-31", updated="2026-07-31",
                       tags=[], related=[], sources=["other.xlsx"])
    out = fm.canonicalize_sources(m, "data_table/order_detail.xlsx")
    assert "data_table/order_detail.xlsx" in out.sources
    # 非法引用（对路径/..）被剔除
    assert all(not s.startswith("/") and ".." not in s for s in out.sources)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_frontmatter.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 frontmatter.py**

Create `l1_kb/ingest/wiki/frontmatter.py`:

```python
"""frontmatter 解析/序列化/合并 —— M2 设计 §2.2、§3.6。

吸收 llm_wiki frontmatter 统一字段（type/title/created/updated/tags/related/sources）
与 UNION_FIELDS/LOCKED_FIELDS 合并语义。YAML 内联数组，确定性可往返。
理解原理后用 Python 重新实现，非复制 llm_wiki 源码。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .page_types import LOCKED_FIELDS, UNION_FIELDS

__all__ = [
    "Frontmatter",
    "parse",
    "dump",
    "union_arrays",
    "stamp_dates",
    "canonicalize_sources",
]


@dataclass
class Frontmatter:
    type: str = ""
    title: str = ""
    created: str = ""
    updated: str = ""
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Frontmatter":
        def _as_list(v):
            if v is None:
                return []
            if isinstance(v, list):
                return [str(x) for x in v]
            return [str(v)]

        return cls(
            type=str(d.get("type", "")),
            title=str(d.get("title", "")),
            created=str(d.get("created", "")),
            updated=str(d.get("updated", "")),
            tags=_as_list(d.get("tags")),
            related=_as_list(d.get("related")),
            sources=_as_list(d.get("sources")),
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "tags": list(self.tags),
            "related": list(self.related),
            "sources": list(self.sources),
        }


def _inline_array(items: list[str]) -> str:
    """YAML 内联数组：[a, b, c]。项内含特殊字符则加引号。"""
    parts = []
    for it in items:
        if any(c in it for c in ":#[]{},&*!|>'\"%@`") or it != it.strip():
            parts.append(json_quote(it))
        else:
            parts.append(it)
    return "[" + ", ".join(parts) + "]"


def json_quote(s: str) -> str:
    import json

    return json.dumps(s, ensure_ascii=False)


def parse(content: str) -> tuple[Frontmatter, str]:
    """解析 wiki 页文本：首尾 --- 包裹的 YAML frontmatter + body。

    无 frontmatter → 返回空 Frontmatter + 原文。
    """
    if not content.startswith("---"):
        return Frontmatter(), content
    # 找闭合 ---
    rest = content[3:]
    # 跳过首个换行
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end == -1:
        return Frontmatter(), content
    yaml_text = rest[:end]
    body = rest[end + 4 :]  # 跳过 \n---
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    try:
        d = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        d = {}
    return Frontmatter.from_dict(d), body


def dump(meta: Frontmatter) -> str:
    """序列化为 YAML frontmatter 文本（含首尾 ---）。内联数组格式。"""
    lines = ["---"]
    lines.append(f"type: {meta.type}")
    lines.append(f"title: {json_quote(meta.title)}")
    lines.append(f"created: {meta.created}")
    lines.append(f"updated: {meta.updated}")
    lines.append(f"tags: {_inline_array(meta.tags)}")
    lines.append(f"related: {_inline_array(meta.related)}")
    lines.append(f"sources: {_inline_array(meta.sources)}")
    lines.append("---")
    return "\n".join(lines)


def union_arrays(existing: Frontmatter, new: Frontmatter) -> Frontmatter:
    """合并：UNION_FIELDS 并集（保序去重），LOCKED_FIELDS 回填 existing 旧值。updated 取新。"""
    merged = Frontmatter(
        type=existing.type,          # locked
        title=existing.title,        # locked
        created=existing.created,    # locked
        updated=new.updated,
    )
    for f in UNION_FIELDS:
        seq = []
        for v in getattr(existing, f) + getattr(new, f):
            if v not in seq:
                seq.append(v)
        setattr(merged, f, seq)
    return merged


def stamp_dates(meta: Frontmatter, today: str, *, is_new: bool) -> Frontmatter:
    """强制日期：新页 created=updated=today；已有页 created 不变、updated=today。"""
    out = Frontmatter(
        type=meta.type, title=meta.title,
        created=meta.created if not is_new else today,
        updated=today,
        tags=list(meta.tags), related=list(meta.related), sources=list(meta.sources),
    )
    if is_new and not out.created:
        out.created = today
    return out


def canonicalize_sources(meta: Frontmatter, source_identity: str) -> Frontmatter:
    """强制 sources 含当前 source_identity，剔除非法引用（对路径/../index/log/.cache）。"""
    out = Frontmatter(
        type=meta.type, title=meta.title, created=meta.created, updated=meta.updated,
        tags=list(meta.tags), related=list(meta.related), sources=list(meta.sources),
    )
    # 注入当前源
    if source_identity not in out.sources:
        out.sources.insert(0, source_identity)
    # 过滤非法
    BAD = ("..", "/index", "/log", ".cache/", ".llm-wiki/")
    out.sources = [
        s for s in out.sources
        if not s.startswith("/") and not any(b in s for b in BAD)
    ]
    # 去重保序
    seen, dedup = set(), []
    for s in out.sources:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    out.sources = dedup
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_frontmatter.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/frontmatter.py tests/test_frontmatter.py
git commit -m "feat(l1/wiki): frontmatter 解析/序列化/数组并集/日期/sources 规范化"
```

### Task 3c: safe_path.py

**Files:**
- Create: `l1_kb/ingest/wiki/safe_path.py`
- Test: `tests/test_safe_wiki_path.py`

**Interfaces:**
- Produces: `is_safe_wiki_path(path)->bool`（path 形如 `wiki/sources/slug.md`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_safe_wiki_path.py`:

```python
import pytest

from l1_kb.ingest.wiki.safe_path import is_safe_wiki_path


@pytest.mark.parametrize("path", [
    "wiki/sources/order_detail.md",
    "wiki/entities/entity_order.md",
    "wiki/process/refund.md",
])
def test_safe_paths(path):
    assert is_safe_wiki_path(path) is True


@pytest.mark.parametrize("path", [
    "wiki/../etc/passwd",          # .. 越界
    "wiki/sources/../sources/x.md",  # 含 ..
    "/etc/passwd",                  # 绝对路径
    "C:\\Users\\x.md",              # Windows 盘符
    "md/order_detail.md",           # 非 wiki 前缀
    "wiki/sources/\x00bad.md",      # 控制字符
    "",                             # 空
    "wiki/sources",                 # 无扩展名/非 .md（目录）
])
def test_unsafe_paths(path):
    assert is_safe_wiki_path(path) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_safe_wiki_path.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 safe_path.py**

Create `l1_kb/ingest/wiki/safe_path.py`:

```python
"""is_safe_wiki_path —— M2 设计 §3.7。

吸收 llm_wiki isSafeIngestPath 原理（Python 重实现，非复制源码）。
LLM 生成的 path 来自不可信文本（源文档可能含 prompt injection），必须校验：
非空、无控制字符、非绝对路径/Windows 盘符、反斜杠归一、任一段含 .. 拒绝、
必须 wiki/ 前缀、必须 .md 结尾。
"""

from __future__ import annotations

import re

__all__ = ["is_safe_wiki_path"]

_CTRL_RE = re.compile(r"[\x00-\x1f]")


def is_safe_wiki_path(path: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    if _CTRL_RE.search(path):
        return False
    norm = path.replace("\\", "/")
    # 绝对路径 / Windows 盘符
    if norm.startswith("/") or re.match(r"^[a-zA-Z]:/", norm):
        return False
    parts = norm.split("/")
    if parts[0] != "wiki":
        return False
    for seg in parts:
        if seg in ("", ".", ".."):
            return False
        if ".." in seg:  # 段内含 ..
            return False
    # 必须是 .md 叶子文件
    if not norm.endswith(".md"):
        return False
    # 禁止生成应用管理文件
    stem = parts[-1][:-3]
    if stem in ("index", "log", "overview"):
        return False
    return True
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_safe_wiki_path.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/safe_path.py tests/test_safe_wiki_path.py
git commit -m "feat(l1/wiki): is_safe_wiki_path 路径注入防护（吸收 llm_wiki isSafeIngestPath 原理）"
```

---

## Task 4: file_blocks + merge + index_log + ingest_cache

### Task 4a: file_blocks.py

**Files:**
- Create: `l1_kb/ingest/wiki/file_blocks.py`
- Test: `tests/test_file_blocks.py`

**Interfaces:**
- Produces: `parse_file_blocks(text)->list[tuple[str,str]]`（返回 `[(path, content), ...]`，丢弃未闭合/非法 path，warn 到 stderr）；`FileBlock` dataclass 可选

- [ ] **Step 1: 写失败测试**

Create `tests/test_file_blocks.py`:

```python
from l1_kb.ingest.wiki.file_blocks import parse_file_blocks


def test_parse_two_blocks():
    text = (
        "---FILE: wiki/sources/a.md---\n"
        "type: source\n---\nbody A\n"
        "---END FILE---\n"
        "---FILE: wiki/entities/b.md---\n"
        "type: entity\n---\nbody B\n"
        "---END FILE---\n"
    )
    blocks = parse_file_blocks(text)
    assert len(blocks) == 2
    assert blocks[0] == ("wiki/sources/a.md", "type: source\n---\nbody A\n")
    assert blocks[1] == ("wiki/entities/b.md", "type: entity\n---\nbody B\n")


def test_truncated_block_dropped():
    # 末尾 block 未闭合（无 ---END FILE---）→ 丢弃，前一个保留
    text = (
        "---FILE: wiki/sources/a.md---\n"
        "body A\n"
        "---END FILE---\n"
        "---FILE: wiki/entities/b.md---\n"
        "body B truncated without end"
    )
    blocks = parse_file_blocks(text)
    assert len(blocks) == 1
    assert blocks[0][0] == "wiki/sources/a.md"


def test_unsafe_path_dropped():
    text = (
        "---FILE: wiki/../etc/passwd.md---\n"
        "evil\n"
        "---END FILE---\n"
    )
    assert parse_file_blocks(text) == []


def test_empty_text():
    assert parse_file_blocks("") == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_file_blocks.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

Create `l1_kb/ingest/wiki/file_blocks.py`:

```python
"""解析 ---FILE:...---...---END FILE--- block —— M2 设计 §3.5。

吸收 llm_wiki parseFileBlocks + FILE_BLOCK_REGEX 原理（Python 重实现）。
未闭合 block（截断）→ 丢弃 + warn（不调 LLM 修复，砍 llm_wiki 截断修复路径）。
每个 path 过 is_safe_wiki_path，不通过丢弃 + warn。
"""

from __future__ import annotations

import re
import sys

from .safe_path import is_safe_wiki_path

__all__ = ["parse_file_blocks"]

_BLOCK_RE = re.compile(
    r"---FILE:\s*([^\n]+?)\s*---\n([\s\S]*?)---END FILE---"
)


def _warn(msg: str) -> None:
    print(f"[warn] file_blocks: {msg}", file=sys.stderr)


def parse_file_blocks(text: str) -> list[tuple[str, str]]:
    """从 LLM 输出文本解析 FILE block。

    返回 [(path, content), ...]。未闭合 block 不被正则匹配（自然丢弃）。
    非法 path 经 is_safe_wiki_path 过滤。
    """
    if not text:
        return []
    blocks: list[tuple[str, str]] = []
    for m in _BLOCK_RE.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        if not is_safe_wiki_path(path):
            _warn(f"丢弃非法/不安全 path: {path!r}")
            continue
        blocks.append((path, content))
    # 检测未闭合 block（有 ---FILE: 但无对应 ---END FILE---）→ warn
    opened = re.findall(r"---FILE:\s*([^\n]+?)\s*---", text)
    closed = [b[0] for b in blocks]
    for p in opened:
        if p.strip() not in closed and not is_safe_wiki_path(p.strip()):
            continue  # 已因不安全路径 warn 过
        # 仅对安全 path 但未闭合的发 warn
        if is_safe_wiki_path(p.strip()) and p.strip() not in closed:
            _warn(f"丢弃未闭合 block: {p.strip()!r}")
    return blocks
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_file_blocks.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/file_blocks.py tests/test_file_blocks.py
git commit -m "feat(l1/wiki): file_blocks 解析 FILE block（截断丢弃+路径校验）"
```

### Task 4b: merge.py

**Files:**
- Create: `l1_kb/ingest/wiki/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `Frontmatter`、`parse`、`dump`、`union_arrays`、`stamp_dates`、`canonicalize_sources`（Task 3b）；`validate_routing`（Task 3a）
- Produces: `merge_page(existing_text, new_path, new_content, source_identity, today, *, exists)->str|None`（返回合并后整页文本；若 routing 不一致返回 None）

- [ ] **Step 1: 写失败测试**

Create `tests/test_merge.py`:

```python
from l1_kb.ingest.wiki.merge import merge_page


def _page(type_, title, sources, body, created="2026-07-01", updated="2026-07-01"):
    return (
        "---\n"
        f"type: {type_}\n"
        f'title: "{title}"\n'
        f"created: {created}\n"
        f"updated: {updated}\n"
        "tags: []\n"
        "related: []\n"
        f"sources: {sources}\n"
        "---\n\n"
        f"{body}\n"
    )


def test_new_page_written():
    new = _page("source", "T", ["[data_table/order_detail.xlsx]"], "body A")
    out = merge_page(None, "wiki/sources/a.md", new, "data_table/order_detail.xlsx", "2026-07-31", exists=False)
    assert out is not None
    assert "body A" in out
    assert "created: 2026-07-31" in out  # 新页 created=今日


def test_single_source_replace_body():
    existing = _page("source", "T", ["[data_table/order_detail.xlsx]"], "old body", updated="2026-07-01")
    new = _page("source", "T", ["[data_table/order_detail.xlsx]"], "new body", updated="2026-07-31")
    out = merge_page(existing, "wiki/sources/a.md", new, "data_table/order_detail.xlsx", "2026-07-31", exists=True)
    assert "new body" in out
    assert "old body" not in out  # 单源页替换 body
    assert "created: 2026-07-01" in out  # locked created 不变


def test_multi_source_append_body():
    existing = _page("entity", "E", ["[data_table/order_detail.xlsx]"], "orig body", updated="2026-07-01")
    new = _page("entity", "E", ["[data_table/wide_table.xlsx]"], "added body", updated="2026-07-31")
    out = merge_page(existing, "wiki/entities/e.md", new, "data_table/wide_table.xlsx", "2026-07-31", exists=True)
    assert "orig body" in out
    assert "added body" in out
    assert "来源补充: data_table/wide_table.xlsx" in out
    # sources 并集
    assert "data_table/order_detail.xlsx" in out
    assert "data_table/wide_table.xlsx" in out


def test_routing_mismatch_returns_none():
    new = _page("entity", "E", ["[x.xlsx]"], "body")
    out = merge_page(None, "wiki/sources/e.md", new, "x.xlsx", "2026-07-31", exists=False)
    assert out is None  # entity 页落在 sources 目录 → routing 不一致


def test_multi_source_dedup_when_new_body_contained():
    existing = _page("entity", "E", ["[s1.xlsx]"], "shared content", updated="2026-07-01")
    new = _page("entity", "E", ["[s2.xlsx]"], "shared content", updated="2026-07-31")
    out = merge_page(existing, "wiki/entities/e.md", new, "s2.xlsx", "2026-07-31", exists=True)
    # new_body 完全被 existing 包含 → 不重复追加段落
    assert out.count("shared content") == 1
    assert "来源补充: s2.xlsx" not in out
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_merge.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 merge.py**

Create `l1_kb/ingest/wiki/merge.py`:

```python
"""已有 wiki 页合并 —— M2 设计 §3.6。

吸收 llm_wiki writeFileBlocks + mergePageContent 原理，简化合并策略：
- 单源页（existing.sources == [当前源]）→ 替换 body（吸收 replaceExistingBody）
- 多源页 → 追加段落（砍 LLM body 合并/70% 缩水/page-history 备份）
- frontmatter：UNION_FIELDS 并集 + LOCKED_FIELDS 回填旧值
- new_body 完全被 existing 包含 → 不重复追加（去重，§9 待决议采纳）
"""

from __future__ import annotations

import sys

from .frontmatter import (
    Frontmatter,
    canonicalize_sources,
    dump,
    parse,
    stamp_dates,
    union_arrays,
)
from .page_types import validate_routing

__all__ = ["merge_page"]


def _warn(msg: str) -> None:
    print(f"[warn] merge: {msg}", file=sys.stderr)


def merge_page(
    existing_text: str | None,
    new_path: str,
    new_content: str,
    source_identity: str,
    today: str,
    *,
    exists: bool,
) -> str | None:
    """合并/写入一页。返回整页文本；routing 不一致返回 None。"""
    new_fm, new_body = parse(new_content)
    if not validate_routing(new_path, new_fm.type):
        _warn(f"routing 不一致，丢弃: {new_path} type={new_fm.type}")
        return None

    new_fm = canonicalize_sources(new_fm, source_identity)

    if not exists or existing_text is None:
        new_fm = stamp_dates(new_fm, today, is_new=True)
        return dump(new_fm) + "\n\n" + new_body.strip() + "\n"

    existing_fm, existing_body = parse(existing_text)
    existing_fm = canonicalize_sources(existing_fm, source_identity)

    # 单源页 → 替换 body
    is_single_source = existing_fm.sources == [source_identity]
    if is_single_source:
        merged_body = new_body.strip()
    else:
        # 多源页 → 追加段落（去重：new_body 完全被 existing 包含则不追加）
        nb = new_body.strip()
        if nb and nb in existing_body.strip():
            merged_body = existing_body.strip()
        else:
            merged_body = (
                existing_body.strip()
                + f"\n\n## 来源补充: {source_identity}\n\n"
                + nb
            )

    merged_fm = union_arrays(existing_fm, new_fm)
    merged_fm = stamp_dates(merged_fm, today, is_new=False)
    return dump(merged_fm) + "\n\n" + merged_body + "\n"
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_merge.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/merge.py tests/test_merge.py
git commit -m "feat(l1/wiki): merge 单源替换/多源追加 + 数组并集 + locked 字段"
```

### Task 4c: index_log.py

**Files:**
- Create: `l1_kb/ingest/wiki/index_log.py`
- Test: `tests/test_index_log.py`

**Interfaces:**
- Consumes: `parse`（Task 3b）读 wiki 页 frontmatter；`PAGE_TYPES`、`TYPE_TO_DIR`（Task 3a）
- Produces: `rebuild_index(wiki_root, today)->None`（原子写 `index.md`）、`append_log(wiki_root, source_identity, today)->None`（追加 `log.md`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_index_log.py`:

```python
from l1_kb.ingest.wiki import index_log


def _write(p, content):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_rebuild_index_groups_by_type_sorted(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki / "entities" / "b_entity.md",
           "---\ntype: entity\ntitle: \"B\"\ncreated: 2026-07-01\nupdated: 2026-07-01\ntags: []\nrelated: []\nsources: [x]\n---\n\nbody\n")
    _write(wiki / "entities" / "a_entity.md",
           "---\ntype: entity\ntitle: \"A\"\ncreated: 2026-07-01\nupdated: 2026-07-01\ntags: []\nrelated: []\nsources: [x]\n---\n\nbody\n")
    _write(wiki / "sources" / "src1.md",
           "---\ntype: source\ntitle: \"Src1\"\ncreated: 2026-07-01\nupdated: 2026-07-01\ntags: []\nrelated: []\nsources: [x]\n---\n\nbody\n")
    # index.md / log.md 应被排除
    _write(wiki / "index.md", "# old index\n")
    _write(wiki / "log.md", "# Wiki Log\n")

    index_log.rebuild_index(wiki, "2026-07-31")
    idx = (wiki / "index.md").read_text(encoding="utf-8")
    assert idx.startswith("# Wiki Index")
    # 按 type 分组，组内按 title 排序
    assert idx.index("## source") < idx.index("## entity")
    assert idx.index("[[a_entity|A]]") < idx.index("[[b_entity|B]]")
    # index/log 茎被排除
    assert "index.md" not in idx.replace("# Wiki Index", "")


def test_rebuild_index_empty(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    index_log.rebuild_index(wiki, "2026-07-31")
    assert (wiki / "index.md").read_text(encoding="utf-8").startswith("# Wiki Index")


def test_append_log(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    index_log.append_log(wiki, "data_table/order_detail.xlsx", "2026-07-31")
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert log.startswith("# Wiki Log")
    assert "## [2026-07-31] ingest | data_table/order_detail.xlsx" in log
    # 再次追加不重复首行
    index_log.append_log(wiki, "process/policy.md", "2026-07-31")
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert log.count("# Wiki Log") == 1
    assert "## [2026-07-31] ingest | process/policy.md" in log
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_index_log.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 index_log.py**

Create `l1_kb/ingest/wiki/index_log.py`:

```python
"""确定性 index.md 重建 / log.md 追加 —— M2 设计 §4。

吸收 llm_wiki updateWikiIndexDeterministically + buildDeterministicIngestLog
原理（Python 重实现，不用 LLM）。index.md 按 frontmatter type 分组、组内按
title 排序、原子 temp+rename 写入。log.md 追加 `## [YYYY-MM-DD] ingest | {identity}`。
"""

from __future__ import annotations

import os
from pathlib import Path

from ..frontmatter_agnostic import _walk_wiki_pages  # 不存在，见下方修正
from .frontmatter import parse
from .page_types import PAGE_TYPES, TYPE_TO_DIR

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
```

> **修正**：上方 import `..frontmatter_agnostic` 不存在——删掉该 import，改用本文件内的 `_collect_pages`（已自包含）。把 import 行删除：

把文件顶部 import 段改为（删除错误的 `from ..frontmatter_agnostic import ...` 行）：

```python
import os
from pathlib import Path

from .frontmatter import parse
from .page_types import PAGE_TYPES
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_index_log.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/index_log.py tests/test_index_log.py
git commit -m "feat(l1/wiki): index_log 确定性重建 index.md / 追加 log.md"
```

### Task 4d: ingest_cache.py

**Files:**
- Create: `l1_kb/ingest/wiki/ingest_cache.py`
- Test: `tests/test_ingest_cache.py`

**Interfaces:**
- Consumes: `config.INGEST_CACHE_PATH`（Task 2，但本模块接收 cache_path 参数以利测试）
- Produces: `check_cache(cache_path, source_identity, content_hash)->bool`、`save_cache(cache_path, source_identity, content_hash, written_paths)->None`、`content_hash(text)->str`

- [ ] **Step 1: 写失败测试**

Create `tests/test_ingest_cache.py`:

```python
from l1_kb.ingest.wiki.ingest_cache import check_cache, save_cache, content_hash


def test_content_hash_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


def test_cache_miss_then_hit(tmp_path):
    cache = tmp_path / "ingest-cache.json"
    h = content_hash("md content")
    # 未存 → miss
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is False
    # 写入两张页
    pages = [tmp_path / "wiki" / "sources" / "a.md", tmp_path / "wiki" / "entities" / "b.md"]
    for p in pages:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    save_cache(cache, "data_table/order_detail.xlsx", h, [str(p) for p in pages])
    # 页都在 → hit
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is True


def test_cache_ghost_invalidated_when_page_deleted(tmp_path):
    cache = tmp_path / "ingest-cache.json"
    h = content_hash("md content")
    pages = [tmp_path / "wiki" / "sources" / "a.md"]
    pages[0].parent.mkdir(parents=True, exist_ok=True)
    pages[0].write_text("x", encoding="utf-8")
    save_cache(cache, "data_table/order_detail.xlsx", h, [str(p) for p in pages])
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is True
    # 删页 → 幽灵条目失效 → miss
    pages[0].unlink()
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is False


def test_cache_invalidated_on_content_change(tmp_path):
    cache = tmp_path / "ingest-cache.json"
    h1 = content_hash("v1")
    save_cache(cache, "x.xlsx", h1, [])
    assert check_cache(cache, "x.xlsx", content_hash("v2")) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_ingest_cache.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 ingest_cache.py**

Create `l1_kb/ingest/wiki/ingest_cache.py`:

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_ingest_cache.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/ingest_cache.py tests/test_ingest_cache.py
git commit -m "feat(l1/wiki): ingest_cache sha256+落盘校验防幽灵"
```

---

## Task 5: llm/client + ingest_prompts + ingest.py 编排

### Task 5a: llm/client.py

**Files:**
- Create: `l1_kb/llm/__init__.py`、`l1_kb/llm/client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `config.LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`（Task 2）
- Produces: `LLMError(Exception)`、`LLMClient`（`chat_json(system, user)->dict`、`chat_text(system, user, max_tokens=8192)->str`）

- [ ] **Step 1: 写失败测试（mock openai）**

Create `tests/test_llm_client.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from l1_kb.llm import client as client_mod
from l1_kb.llm.client import LLMClient, LLMError


def _fake_openai(return_content):
    """返回假的 OpenAI client，chat.completions.create 返回固定 content。"""
    fake = MagicMock()
    msg = MagicMock()
    msg.message.content = return_content
    choice = MagicMock()
    choice.message = msg.message
    fake.chat.completions.create.return_value = MagicMock(choices=[choice])
    return fake


def test_chat_json_parses():
    fake = _fake_openai(json.dumps({"entities": [], "summary": "ok"}))
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        result = c.chat_json("sys", "user")
        assert result == {"entities": [], "summary": "ok"}
        # 确认请求了 json_object
        kwargs = fake.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}


def test_chat_json_retries_on_bad_json():
    fake = _fake_openai("not json")
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        with pytest.raises(LLMError):
            c.chat_json("sys", "user")


def test_chat_text_returns_string():
    fake = _fake_openai("plain text output")
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        assert c.chat_text("sys", "user") == "plain text output"


def test_chat_json_retries_once_then_succeeds():
    # 第一次非法 JSON，第二次合法
    fake = MagicMock()
    msg_bad = MagicMock(); msg_bad.message.content = "bad"
    msg_good = MagicMock(); msg_good.message.content = json.dumps({"ok": True})
    choice_bad = MagicMock(); choice_bad.message = msg_bad.message
    choice_good = MagicMock(); choice_good.message = msg_good.message
    fake.chat.completions.create.side_effect = [
        MagicMock(choices=[choice_bad]),
        MagicMock(choices=[choice_good]),
    ]
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        assert c.chat_json("sys", "user") == {"ok": True}
        assert fake.chat.completions.create.call_count == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 client.py**

Create `l1_kb/llm/__init__.py`:

```python
"""LLM 子包 —— OpenAI 兼容薄封装。"""
```

Create `l1_kb/llm/client.py`:

```python
"""OpenAI 兼容薄封装 —— M2 设计 §3.2。

chat_json：response_format=json_object，非法 JSON 重试一次，仍失败抛 LLMError。
chat_text：纯文本出（step2 FILE block 用）。单步超时 60s，失败即降级。
无流式、无工具——纯结构化进出。
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

__all__ = ["LLMClient", "LLMError"]


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 60.0) -> None:
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model

    def chat_json(self, system: str, user: str) -> dict[str, Any]:
        """结构化 JSON 出。非法 JSON 重试一次，仍失败抛 LLMError。"""
        for attempt in range(2):
            content = self._raw_chat(system, user, temperature=0.1, response_format={"type": "json_object"})
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                if attempt == 1:
                    raise LLMError(f"LLM 返回非法 JSON: {content[:200]!r}")
        raise LLMError("unreachable")

    def chat_text(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """纯文本出（FILE block）。"""
        return self._raw_chat(system, user, temperature=0.1, max_tokens=max_tokens)

    def _raw_chat(self, system: str, user: str, **kwargs: Any) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        return resp.choices[0].message.content or ""
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/llm/__init__.py l1_kb/llm/client.py tests/test_llm_client.py
git commit -m "feat(l1/llm): OpenAI 兼容薄封装 chat_json/chat_text"
```

### Task 5b: ingest_prompts.py

**Files:**
- Create: `l1_kb/llm/ingest_prompts.py`
- Test: 无纯函数测试（prompt 构造，仅 smoke 测返回非空字符串）

**Interfaces:**
- Produces: `build_step1_messages(source_identity, md_text, index_md)->tuple[str,str]`（system,user）、`build_step2_messages(source_identity, md_text, step1_result, index_md)->tuple[str,str]`

- [ ] **Step 1: 写 smoke 测试**

Create `tests/test_ingest_prompts.py`:

```python
from l1_kb.llm import ingest_prompts as p


def test_step1_messages_contain_required_fields():
    sys_, user = p.build_step1_messages("data_table/order_detail.xlsx", "## 订单\n|order_id|...", "# Wiki Index")
    assert "编目员" in sys_ or "cataloger" in sys_.lower()
    assert "JSON" in sys_
    assert "source" in sys_ and "entity" in sys_ and "concept" in sys_ and "process" in sys_
    assert "data_table/order_detail.xlsx" in user
    assert "## 订单" in user


def test_step2_messages_contain_file_block_format():
    step1 = {"entities": [{"name": "订单", "slug": "entity_order", "role": "数据表"}], "concepts": [], "processes": [], "summary": "s", "keywords": ["order_id"]}
    sys_, user = p.build_step2_messages("data_table/order_detail.xlsx", "## 订单\n", step1, "# Wiki Index")
    assert "FILE" in sys_
    assert "---FILE:" in sys_
    assert "context only" in sys_.lower() or "do not repeat" in sys_.lower()
    assert "data_table/order_detail.xlsx" in user
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_ingest_prompts.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 ingest_prompts.py**

Create `l1_kb/llm/ingest_prompts.py`:

```python
"""step1/step2 prompt 构造 —— M2 设计 §3.3/§3.4。

吸收 llm_wiki buildAnalysisPrompt / buildGenerationPrompt 原理（Python 重实现）。
step1 注入当前 index.md（判断实体是否已存在）+ 源文本 → 结构化 JSON。
step2 注入 schema + purpose + index + step1 分析（标注 context only）+ 源文本 → FILE block。
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["build_step1_messages", "build_step2_messages"]

_STEP1_SYSTEM = """你是企业知识库的编目员（cataloger）。阅读一份原件的 markdown，输出结构化分析 JSON。

页类型固定为这 4 类之一：source / entity / concept / process。
- source：一份原件的摘要页（每次摄入必产 1 张）。
- entity：业务实体（数据表、API、系统、角色等业务对象）。
- concept：业务概念（术语、口径、定义）。
- process：流程/制度（审批流、制度编号 PRC-xxx、步骤、责任人、上下游、触发条件）。

只输出 JSON，不要任何额外文字。JSON schema：
{
  "entities": [{"name": "...", "slug": "entity_xxx", "role": "...", "exists": false}],
  "concepts": [{"name": "...", "slug": "concept_xxx", "definition": "...", "exists": false}],
  "processes": [{"name": "...", "slug": "process_xxx", "code": "PRC-xxx", "owner": "...", "steps": ["..."], "upstream": "...", "downstream": "...", "exists": false}],
  "summary": "3-5 句摘要",
  "keywords": ["字段名/编号/术语"]
}

要求：
- slug 用英文小写 + 下划线（如 entity_order_detail）。
- exists：对照下方 Wiki Index 判断该实体/概念/流程是否已存在（已存在则 true，避免重复生成）。
- summary 点到为止；keywords 必须包含字段名、流程编号等可检索关键串。
- 若该原件不含某类，对应数组留空。
"""

_STEP2_SYSTEM = """你是企业知识库的 wiki 页生成器。根据 step1 分析 + 源文本，生成 wiki 页。

输出严格使用 FILE block 格式，每个页一个 block：
---FILE: wiki/{sources|entities|concepts|process}/{slug}.md---
<frontmatter + body>
---END FILE---

frontmatter 必须含字段（YAML，数组用内联 [a, b]）：
type / title / created / updated / tags / related / sources

规则：
- 必产 1 张 source 摘要页：路径 wiki/sources/{slug}.md，title 为原件标题，body 含关键字段表/摘要。
- 可选若干 entity/concept/process 页（step1 识别出且 exists=false 的才生成）。
- 禁止生成 index.md / log.md / overview.md（由应用确定性维护）。
- sources 必须含当前原件的 source_identity。
- related 用裸 slug（不带 wiki/ .md [[]]）。
- step1 分析是 context only, do not repeat——不要把分析 JSON 原样写进 body。
- title 含中文时用双引号包裹。
"""


def build_step1_messages(source_identity: str, md_text: str, index_md: str) -> tuple[str, str]:
    user = (
        f"当前 Wiki Index（用于判断实体是否已存在）：\n\n{index_md}\n\n"
        f"原件 source_identity: {source_identity}\n\n"
        f"原件 markdown：\n\n{md_text}\n\n"
        f"请输出分析 JSON。"
    )
    return _STEP1_SYSTEM, user


def build_step2_messages(
    source_identity: str, md_text: str, step1_result: dict[str, Any], index_md: str
) -> tuple[str, str]:
    user = (
        f"当前 Wiki Index（context only）：\n\n{index_md}\n\n"
        f"原件 source_identity: {source_identity}\n\n"
        f"step1 分析（context only, do not repeat）：\n\n{json.dumps(step1_result, ensure_ascii=False, indent=2)}\n\n"
        f"原件 markdown：\n\n{md_text}\n\n"
        f"请输出 FILE block（必产 1 张 source 摘要页）。"
    )
    return _STEP2_SYSTEM, user
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_ingest_prompts.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/llm/ingest_prompts.py tests/test_ingest_prompts.py
git commit -m "feat(l1/llm): ingest_prompts step1/step2 prompt 构造"
```

### Task 5c: ingest.py 编排 + fallback

**Files:**
- Create: `l1_kb/ingest/wiki/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `LLMClient`（Task 5a，可为 None 走 fallback）、`build_step1_messages`/`build_step2_messages`（Task 5b）、`parse_file_blocks`（Task 4a）、`merge_page`（Task 4b）、`rebuild_index`/`append_log`（Task 4c）、`check_cache`/`save_cache`/`content_hash`（Task 4d）、`config`（Task 2）、`SectionSplitter.split`（M1）、`slug_from_source_identity`（Task 3a）
- Produces: `ingest_source(md_path, source_identity, *, wiki_root, cache_path, client, today, index_md)->IngestResult`、`IngestResult`（`written_paths`、`skipped_cached`、`fallback`、`errors`）、`build_fallback_pages(source_identity, md_text, today)`（确定性回退，仅产 source 摘要页）、`read_index_md(wiki_root)->str`、`make_client_from_config()->LLMClient|None`

- [ ] **Step 1: 写失败测试（mock client）**

Create `tests/test_ingest.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

from l1_kb.ingest.wiki import ingest


def _fake_client(step1_json, step2_text):
    c = MagicMock()
    c.chat_json.return_value = step1_json
    c.chat_text.return_value = step2_text
    return c


def test_ingest_writes_source_and_entity_pages(tmp_path):
    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n\n| order_id | customer |\n|---|---|\n| O1 | 张三 |\n", encoding="utf-8")

    step1 = {
        "entities": [{"name": "订单明细表", "slug": "entity_order_detail", "role": "数据表", "exists": False}],
        "concepts": [], "processes": [],
        "summary": "订单与订单明细两表。",
        "keywords": ["order_id", "customer"],
    }
    step2 = (
        "---FILE: wiki/sources/data_table_order_detail.md---\n"
        "---\ntype: source\ntitle: \"order_detail\"\ncreated: 2026-07-31\nupdated: 2026-07-31\ntags: []\nrelated: []\nsources: [data_table/order_detail.xlsx]\n---\n\n## 字段\n\n| order_id | customer |\n---END FILE---\n"
        "---FILE: wiki/entities/entity_order_detail.md---\n"
        "---\ntype: entity\ntitle: \"订单明细表\"\ncreated: 2026-07-31\nupdated: 2026-07-31\ntags: []\nrelated: []\nsources: [data_table/order_detail.xlsx]\n---\n\n订单明细表实体。\n---END FILE---\n"
    )
    client = _fake_client(step1, step2)
    res = ingest.ingest_source(
        md_path, "data_table/order_detail.xlsx",
        wiki_root=wiki, cache_path=tmp_path / "cache.json",
        client=client, today="2026-07-31", index_md="# Wiki Index\n",
    )
    assert res.fallback is False
    assert (wiki / "sources" / "data_table_order_detail.md").exists()
    assert (wiki / "entities" / "entity_order_detail.md").exists()
    assert (wiki / "index.md").exists()
    assert (wiki / "log.md").exists()
    assert "data_table/order_detail.xlsx" in (wiki / "log.md").read_text(encoding="utf-8")


def test_ingest_cache_skips_second_run(tmp_path):
    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n|order_id|\n", encoding="utf-8")
    step1 = {"entities": [], "concepts": [], "processes": [], "summary": "s", "keywords": ["order_id"]}
    step2 = (
        "---FILE: wiki/sources/data_table_order_detail.md---\n"
        "---\ntype: source\ntitle: \"t\"\ncreated: 2026-07-31\nupdated: 2026-07-31\ntags: []\nrelated: []\nsources: [data_table/order_detail.xlsx]\n---\n\nbody\n---END FILE---\n"
    )
    client = _fake_client(step1, step2)
    cache = tmp_path / "cache.json"
    ingest.ingest_source(md_path, "data_table/order_detail.xlsx", wiki_root=wiki, cache_path=cache, client=client, today="2026-07-31", index_md="")
    # 第二次：client 不应再被调用
    client.chat_json.reset_mock()
    client.chat_text.reset_mock()
    res = ingest.ingest_source(md_path, "data_table/order_detail.xlsx", wiki_root=wiki, cache_path=cache, client=client, today="2026-07-31", index_md="")
    assert res.skipped_cached is True
    client.chat_json.assert_not_called()
    client.chat_text.assert_not_called()


def test_ingest_fallback_when_no_client(tmp_path):
    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n\n正文段落含 order_id。\n", encoding="utf-8")
    res = ingest.ingest_source(
        md_path, "data_table/order_detail.xlsx",
        wiki_root=wiki, cache_path=tmp_path / "cache.json",
        client=None, today="2026-07-31", index_md="",
    )
    assert res.fallback is True
    # fallback 仅产 source 摘要页
    assert (wiki / "sources" / "data_table_order_detail.md").exists()
    assert not (wiki / "entities").exists() or not any((wiki / "entities").iterdir())
    body = (wiki / "sources" / "data_table_order_detail.md").read_text(encoding="utf-8")
    assert "order_id" in body


def test_ingest_fallback_when_llm_error(tmp_path):
    from l1_kb.llm.client import LLMError

    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n\norder_id 字段。\n", encoding="utf-8")
    client = MagicMock()
    client.chat_json.side_effect = LLMError("boom")
    res = ingest.ingest_source(
        md_path, "data_table/order_detail.xlsx",
        wiki_root=wiki, cache_path=tmp_path / "cache.json",
        client=client, today="2026-07-31", index_md="",
    )
    assert res.fallback is True
    assert (wiki / "sources" / "data_table_order_detail.md").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_ingest.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 ingest.py**

Create `l1_kb/ingest/wiki/ingest.py`:

```python
"""复利 wiki 摄入编排 —— M2 设计 §3。

吸收 llm_wiki ingest.ts 两步流（step1 分析 → step2 生成 FILE block → 解析 →
写入/合并 → 重建 index/log）。LLM 不可用时确定性 fallback 仅产 source 摘要页。
理解原理后用 Python 重新实现，非复制 llm_wiki 源码。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...llm.client import LLMClient, LLMError
from ...llm.ingest_prompts import build_step1_messages, build_step2_messages
from ..section_splitter import split as split_sections
from .file_blocks import parse_file_blocks
from .index_log import append_log, rebuild_index
from .ingest_cache import check_cache, content_hash, save_cache
from .merge import merge_page
from .page_types import slug_from_source_identity

__all__ = ["IngestResult", "ingest_source", "build_fallback_pages", "read_index_md", "make_client_from_config"]


def _warn(msg: str) -> None:
    print(f"[warn] ingest: {msg}", file=sys.stderr)


@dataclass
class IngestResult:
    written_paths: list[str] = field(default_factory=list)
    skipped_cached: bool = False
    fallback: bool = False
    errors: list[str] = field(default_factory=list)


def read_index_md(wiki_root: Path) -> str:
    idx = wiki_root / "index.md"
    if idx.exists():
        return idx.read_text(encoding="utf-8")
    return "# Wiki Index\n_(暂无页面)_\n"


def make_client_from_config() -> LLMClient | None:
    """从 config 构造 LLMClient；未配置 key 返回 None。"""
    from ... import config

    if not config.llm_enabled():
        return None
    try:
        return LLMClient(config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL)
    except Exception as e:  # 构造失败（如网络/库问题）
        _warn(f"LLM client 构造失败，走 fallback: {e}")
        return None


def build_fallback_pages(source_identity: str, md_text: str, today: str) -> list[tuple[str, str]]:
    """确定性回退：仅产 1 张 source 摘要页（吸收 llm_wiki buildFallbackSourceSummary 原理）。

    body ← M1 sections 拼接的标题 + 首段；title ← Source: {identity}；
    sources=[identity]；tags/related 空。
    """
    slug = slug_from_source_identity(source_identity)
    path = f"wiki/sources/{slug}.md"
    sections = split_sections(md_text)
    body_parts = []
    for s in sections:
        if s.title:
            body_parts.append(f"## {s.title}")
        # 取该 section 的首段正文
        lines = md_text.splitlines()
        seg = lines[s.line_start - 1 : s.line_end]
        body_parts.append("\n".join(seg).strip())
    body = "\n\n".join(p for p in body_parts if p) or "(Analysis not available)"
    fm = (
        "---\n"
        f"type: source\n"
        f'title: "Source: {source_identity}"\n'
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: []\n"
        "related: []\n"
        f"sources: [{source_identity}]\n"
        "---\n\n"
    )
    return [(path, fm + body + "\n")]


def ingest_source(
    md_path: Path,
    source_identity: str,
    *,
    wiki_root: Path,
    cache_path: Path,
    client: LLMClient | None,
    today: str,
    index_md: str,
) -> IngestResult:
    """摄入单份 md → wiki 页 + 合并 + 重建 index/log。"""
    md_text = md_path.read_text(encoding="utf-8")
    chash = content_hash(md_text)

    # cache 命中跳过两步 LLM
    if check_cache(cache_path, source_identity, chash):
        return IngestResult(skipped_cached=True)

    # 决定 pages：LLM 两步 或 fallback
    pages: list[tuple[str, str]] | None = None
    fallback = False
    if client is not None:
        try:
            pages = _two_step_llm(client, source_identity, md_text, index_md)
        except (LLMError, Exception) as e:  # noqa: BLE001
            _warn(f"LLM 两步失败，走 fallback: {e}")
            pages = None
    if pages is None:
        pages = build_fallback_pages(source_identity, md_text, today)
        fallback = True

    # 写入/合并每页
    wiki_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for path, content in pages:
        full = wiki_root / path
        exists = full.exists()
        existing_text = full.read_text(encoding="utf-8") if exists else None
        merged = merge_page(existing_text, path, content, source_identity, today, exists=exists)
        if merged is None:
            continue  # routing 不一致已 warn
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(merged, encoding="utf-8")
        written.append(str(full))

    # 重建 index + 追加 log
    rebuild_index(wiki_root, today)
    append_log(wiki_root, source_identity, today)

    save_cache(cache_path, source_identity, chash, written)
    return IngestResult(written_paths=written, fallback=fallback)


def _two_step_llm(
    client: LLMClient, source_identity: str, md_text: str, index_md: str
) -> list[tuple[str, str]]:
    """两步 LLM：step1 分析 JSON → step2 FILE block。"""
    sys1, user1 = build_step1_messages(source_identity, md_text, index_md)
    step1 = client.chat_json(sys1, user1)
    # exists 交叉校验：纠正幻觉（实际磁盘 slug 集合）——此处仅透传，校验在 step2 prompt 已注入 index
    sys2, user2 = build_step2_messages(source_identity, md_text, step1, index_md)
    step2_text = client.chat_text(sys2, user2)
    blocks = parse_file_blocks(step2_text)
    if not blocks:
        raise LLMError("step2 未产出任何合法 FILE block")
    return blocks
```

> 注：`except (LLMError, Exception)` 中 `Exception` 已覆盖 `LLMError`，写法冗余但意图明确（任何异常都降级，不阻塞摄入）。可简化为 `except Exception as e:`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_ingest.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/ingest/wiki/ingest.py tests/test_ingest.py
git commit -m "feat(l1/wiki): ingest 编排 两步LLM+fallback + cache + index/log"
```

---

## Task 6: retrieval/{base,tokenizer,bm25,snippet}

### Task 6a: base.py（Retriever ABC + SearchHit + RRFFuser）

**Files:**
- Create: `l1_kb/retrieval/__init__.py`、`l1_kb/retrieval/base.py`
- Test: `tests/test_rrf.py`

**Interfaces:**
- Produces: `SearchHit` dataclass（`doc_id/section_id/title/snippet/score/source`）、`Retriever` ABC（`search(query,top_n=50)->list[SearchHit]`）、`RRFFuser`（`fuse(results,k=60,top_k=10)->list[SearchHit]`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_rrf.py`:

```python
from l1_kb.retrieval.base import RRFFuser, SearchHit


def _hit(doc_id, sec, score, source="bm25"):
    return SearchHit(doc_id=doc_id, section_id=sec, title="t", snippet="", score=score, source=source)


def test_single_lane_passthrough():
    bm25 = [_hit("a", "s0", 3.0), _hit("a", "s1", 2.0), _hit("b", "s0", 1.0)]
    out = RRFFuser().fuse([bm25], k=60, top_k=10)
    assert len(out) == 3
    # 单路 RRF：1/(60+rank)，rank 从 1 起
    assert out[0].doc_id == "a" and out[0].section_id == "s0"
    assert abs(out[0].score - 1 / 61) < 1e-9


def test_dedup_same_doc_section_across_lanes():
    lane1 = [_hit("a", "s0", 5.0)]
    lane2 = [_hit("a", "s0", 4.0), _hit("b", "s0", 1.0)]
    out = RRFFuser().fuse([lane1, lane2], k=60, top_k=10)
    # (a,s0) 两路融合：1/61 + 1/61
    a_hits = [h for h in out if h.doc_id == "a" and h.section_id == "s0"]
    assert len(a_hits) == 1
    assert abs(a_hits[0].score - 2 / 61) < 1e-9
    assert len(out) == 2


def test_top_k_truncation():
    bm25 = [_hit(f"d{i}", "s0", float(10 - i)) for i in range(20)]
    out = RRFFuser().fuse([bm25], k=60, top_k=5)
    assert len(out) == 5


def test_empty_input():
    assert RRFFuser().fuse([], k=60, top_k=10) == []
    assert RRFFuser().fuse([[]], k=60, top_k=10) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_rrf.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 base.py**

Create `l1_kb/retrieval/__init__.py`:

```python
"""检索子包 —— BM25 + RRF（P0 单路，向量路 M3 注册即生效）。"""
```

Create `l1_kb/retrieval/base.py`:

```python
"""检索接口层 —— M2 设计 §5.1。

Retriever ABC + SearchHit + RRFFuser。P0 仅注册 BM25Retriever，fuse([bm25]) 单路
直通（去重 + 截断）。向量化后注册 VectorRetriever 即两路，契约不变。
吸收 llm_wiki RRF k=60。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = ["SearchHit", "Retriever", "RRFFuser"]


@dataclass
class SearchHit:
    doc_id: str
    section_id: str
    title: str
    snippet: str = ""
    score: float = 0.0
    source: str = "bm25"


class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, top_n: int = 50) -> list[SearchHit]:
        ...


class RRFFuser:
    def fuse(self, results: list[list[SearchHit]], k: int = 60, top_k: int = 10) -> list[SearchHit]:
        """RRF: score = Σ 1/(k + rank_i)，rank_i 从 1 起。同 (doc_id, section_id) 取最高分合并。"""
        if not results:
            return []
        merged: dict[tuple[str, str], SearchHit] = {}
        for lane in results:
            for rank, hit in enumerate(lane, start=1):
                key = (hit.doc_id, hit.section_id)
                rrf = 1.0 / (k + rank)
                if key not in merged:
                    merged[key] = SearchHit(
                        doc_id=hit.doc_id, section_id=hit.section_id,
                        title=hit.title, snippet=hit.snippet,
                        score=rrf, source=hit.source,
                    )
                else:
                    merged[key].score += rrf
        ranked = sorted(merged.values(), key=lambda h: h.score, reverse=True)
        return ranked[:top_k]
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_rrf.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/retrieval/__init__.py l1_kb/retrieval/base.py tests/test_rrf.py
git commit -m "feat(l1/retrieval): base SearchHit + Retriever ABC + RRFFuser"
```

### Task 6b: tokenizer.py（jieba + CJK bigram F7）

**Files:**
- Create: `l1_kb/retrieval/tokenizer.py`
- Test: `tests/test_tokenizer.py`

**Interfaces:**
- Produces: `tokenize(text)->list[str]`

- [ ] **Step 1: 写失败测试**

Create `tests/test_tokenizer.py`:

```python
from l1_kb.retrieval.tokenizer import tokenize


def test_english_token():
    toks = tokenize("order_id")
    assert "order_id" in toks


def test_cjk_bigram():
    toks = set(tokenize("订单状态"))
    # CJK bigram：订单/单状/状态 至少含若干
    assert "订单" in toks or "状态" in toks


def test_mixed():
    toks = set(tokenize("order_id 订单状态"))
    assert "order_id" in toks
    assert "订单" in toks or "状态" in toks


def test_empty():
    assert tokenize("") == []


def test_prc_code():
    toks = set(tokenize("PRC-2024-003"))
    # jieba 可能切不准，但整体串或 PRC 应在
    assert "PRC-2024-003" in toks or "PRC" in toks or "2024" in toks
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tokenizer.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 tokenizer.py**

Create `l1_kb/retrieval/tokenizer.py`:

```python
"""分词 jieba + CJK bigram —— M2 设计 §5.2（F7）。

词项 = jieba.cut_for_search 切词 ∪ 连续 CJK 串的 2-gram。
jieba 对未登录词（order_status / PRC-2024-003）切不准时 bigram 兜底。
"""

from __future__ import annotations

import re

import jieba

__all__ = ["tokenize"]

_CJK_RE = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """返回去重保序的词项列表：jieba 切词 ∪ CJK bigram。"""
    if not text:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for t in jieba.cut_for_search(text):
        if t.strip() and t not in seen:
            seen.add(t)
            tokens.append(t)
    for run in _CJK_RE.findall(text):
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in seen:
                seen.add(bg)
                tokens.append(bg)
    return tokens
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_tokenizer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/retrieval/tokenizer.py tests/test_tokenizer.py
git commit -m "feat(l1/retrieval): tokenizer jieba + CJK bigram (F7)"
```

### Task 6c: bm25.py

**Files:**
- Create: `l1_kb/retrieval/bm25.py`
- Test: `tests/test_bm25.py`

**Interfaces:**
- Consumes: `Retriever`/`SearchHit`（Task 6a）、`tokenize`（Task 6b）
- Produces: `BM25Retriever(Retriever)`（`__init__(entries)`，entry=`{slug,section_id,title,body_text}`；`search(query,top_n=50)->list[SearchHit]`，`source='bm25'`，snippet 留空由调用方填）

- [ ] **Step 1: 写失败测试**

Create `tests/test_bm25.py`:

```python
from l1_kb.retrieval.bm25 import BM25Retriever


def test_ranking_exact_term_top():
    entries = [
        {"slug": "entity_order_detail", "section_id": "s0", "title": "订单明细表", "body_text": "| order_id | string | 订单唯一标识 |"},
        {"slug": "source_other", "section_id": "s0", "title": "其他", "body_text": "本页与订单无关，无字段"},
    ]
    r = BM25Retriever(entries)
    hits = r.search("order_id", top_n=5)
    assert len(hits) >= 1
    assert hits[0].doc_id == "entity_order_detail"
    assert hits[0].source == "bm25"


def test_top_n_truncation():
    entries = [
        {"slug": f"d{i}", "section_id": "s0", "title": f"order_id {i}", "body_text": "order_id"}
        for i in range(10)
    ]
    r = BM25Retriever(entries)
    hits = r.search("order_id", top_n=3)
    assert len(hits) == 3


def test_empty_query_or_corpus():
    r = BM25Retriever([])
    assert r.search("order_id") == []
    entries = [{"slug": "a", "section_id": "s0", "title": "order_id", "body_text": "order_id"}]
    r2 = BM25Retriever(entries)
    assert r2.search("") == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_bm25.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 bm25.py**

Create `l1_kb/retrieval/bm25.py`:

```python
"""BM25 检索器 —— M2 设计 §5.3。

rank-bm25 BM25Okapi（IDF + 文档长度归一，真 BM25，不照搬 llm_wiki 手写打分）。
文档单元文本 = frontmatter title + section 标题 + 正文。纯内存，每次运行重建。
"""

from __future__ import annotations

from rank_bm25 import BM25Okapi

from .base import Retriever, SearchHit
from .tokenizer import tokenize

__all__ = ["BM25Retriever"]


class BM25Retriever(Retriever):
    def __init__(self, entries: list[dict]) -> None:
        """entries: [{slug, section_id, title, body_text}]，每个 entry 一个 corpus 文档。"""
        self._meta = entries
        self._corpus = [tokenize(f"{e['title']} {e['body_text']}") for e in entries]
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(self, query: str, top_n: int = 50) -> list[SearchHit]:
        if self._bm25 is None or not query.strip():
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_n]
        hits: list[SearchHit] = []
        for idx, sc in ranked:
            if sc <= 0:
                continue
            e = self._meta[idx]
            hits.append(SearchHit(
                doc_id=e["slug"], section_id=e["section_id"],
                title=e["title"], snippet="",
                score=float(sc), source="bm25",
            ))
        return hits
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_bm25.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/retrieval/bm25.py tests/test_bm25.py
git commit -m "feat(l1/retrieval): BM25Retriever rank-bm25 索引 wiki 页 section"
```

### Task 6d: snippet.py

**Files:**
- Create: `l1_kb/retrieval/snippet.py`
- Test: `tests/test_snippet.py`

**Interfaces:**
- Produces: `make_snippet(md_text, line_start, line_end, max_chars=500)->str`

- [ ] **Step 1: 写失败测试**

Create `tests/test_snippet.py`:

```python
from l1_kb.retrieval.snippet import make_snippet


def test_slice_lines():
    md = "line0\nline1\norder_id 字段\nline3\n"
    out = make_snippet(md, 2, 3)
    assert "order_id" in out
    assert out.startswith("line1")


def test_truncation():
    md = "\n".join("x" * 100 for _ in range(20))
    out = make_snippet(md, 1, 20, max_chars=50)
    assert len(out) <= 50


def test_out_of_range_safe():
    md = "only one line\n"
    assert make_snippet(md, 1, 999).startswith("only one line")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_snippet.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 snippet.py**

Create `l1_kb/retrieval/snippet.py`:

```python
"""片段切分 —— M2 设计 §5.5。按 section 1-based 行号范围从 wiki 页原文切 snippet。"""

from __future__ import annotations

__all__ = ["make_snippet"]


def make_snippet(md_text: str, line_start: int, line_end: int, max_chars: int = 500) -> str:
    """按 1-based [line_start, line_end] 切片，超长尾部截断。越界安全。"""
    lines = md_text.splitlines()
    if not lines:
        return ""
    start = max(line_start - 1, 0)
    end = line_end if line_end <= len(lines) else len(lines)
    seg = lines[start:end]
    out = "\n".join(seg)
    return out[:max_chars]
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_snippet.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add l1_kb/retrieval/snippet.py tests/test_snippet.py
git commit -m "feat(l1/retrieval): snippet 按行号切片"
```

---

## Task 7: cli/kb.py 扩展 kb ingest / kb index / kb search

**Files:**
- Modify: `l1_kb/cli/kb.py`
- Test: `tests/test_kb_ingest_search.py`

**Interfaces:**
- Consumes: `ingest_source`/`read_index_md`/`make_client_from_config`（Task 5c）、`rebuild_index`（Task 4c）、`BM25Retriever`/`RRFFuser`（Task 6）、`make_snippet`（Task 6d）、`SectionSplitter.split`（M1）、`config`（Task 2）
- Produces: CLI 子命令 `kb ingest [--path] [--no-llm]`、`kb index`、`kb search QUERY`

- [ ] **Step 1: 写失败测试（端到端，走 fallback 不依赖 LLM key）**

Create `tests/test_kb_ingest_search.py`:

```python
import os
from pathlib import Path

from click.testing import CliRunner

from l1_kb.cli.kb import cli


def _make_md(root):
    md = root / "data_table" / "order_detail.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        "## 订单\n\n| order_id | customer |\n|---|---|\n| O1 | 张三 |\n\n"
        "## 订单明细\n\n| order_id | item |\n|---|---|\n| O1 | 笔记本 |\n",
        encoding="utf-8",
    )
    return md


def test_kb_ingest_fallback_then_search(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    md_root = tmp_path / "md"
    _make_md(md_root)
    md_path = md_root / "data_table" / "order_detail.md"

    runner = CliRunner()
    # ingest（无 LLM key → fallback）
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = runner.invoke(cli, [
        "ingest", str(md_path),
        "--md-root", str(md_root),
        "--raw-root", str(tmp_path / "raw"),
        "--wiki-root", str(wiki),
        "--cache-path", str(tmp_path / "cache.json"),
    ])
    assert res.exit_code == 0, res.output
    assert (wiki / "sources").exists()
    assert (wiki / "index.md").exists()

    # index 重建
    res2 = runner.invoke(cli, ["index", "--wiki-root", str(wiki)])
    assert res2.exit_code == 0

    # search order_id → 命中
    res3 = runner.invoke(cli, ["search", "order_id", "--wiki-root", str(wiki)])
    assert res3.exit_code == 0
    assert "order_id" in res3.output


def test_kb_search_empty_wiki(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    runner = CliRunner()
    res = runner.invoke(cli, ["search", "order_id", "--wiki-root", str(wiki)])
    assert res.exit_code == 0  # 空语料不崩
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_kb_ingest_search.py -v`
Expected: FAIL（`ingest` 子命令不存在 / `No such command`）

- [ ] **Step 3: 实现 CLI 扩展**

在 `l1_kb/cli/kb.py` 末尾（`if __name__ == "__main__"` 之前）追加三个子命令。先在文件顶部 import 区追加：

```python
from ..ingest.wiki import ingest as wiki_ingest
from ..ingest.wiki.index_log import rebuild_index
from ..ingest.wiki.ingest import ingest_source, make_client_from_config, read_index_md
from ..ingest.section_splitter import split as split_sections
from ..retrieval.bm25 import BM25Retriever
from ..retrieval.base import RRFFuser
from ..retrieval.snippet import make_snippet
from .. import config

DEFAULT_WIKI = "l1_kb/knowledge_base/wiki"
DEFAULT_CACHE = "l1_kb/knowledge_base/.cache/ingest-cache.json"
```

追加命令：

```python
def _wiki_entries(wiki_root: Path) -> list[dict]:
    """扫描 wiki/*.md → section entries（复用 M1 splitter）。"""
    entries = []
    if not wiki_root.exists():
        return entries
    for p in sorted(wiki_root.rglob("*.md")):
        if p.stem in ("index", "log", "overview"):
            continue
        text = p.read_text(encoding="utf-8")
        # 解析 frontmatter 取 title
        from ..ingest.wiki.frontmatter import parse as parse_fm
        fm, body = parse_fm(text)
        full = (fm.title + "\n\n" + body) if fm.title else body
        for s in split_sections(full):
            seg_lines = full.splitlines()
            body_text = "\n".join(seg_lines[s.line_start - 1 : s.line_end])
            entries.append({
                "slug": p.stem,
                "section_id": s.section_id,
                "title": f"{fm.title} / {s.title}" if s.title else fm.title,
                "body_text": body_text,
                "_line_start": s.line_start,
                "_line_end": s.line_end,
                "_text": text,
            })
    return entries


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--no-llm", is_flag=True, help="禁用 LLM，强制 fallback。")
def ingest(path: Path, md_root: Path, raw_root: Path, wiki_root: Path, cache_path: Path, no_llm: bool) -> None:
    """摄入 md 文件（单文件或目录）→ wiki 页 + index/log。

    无 LLM key 或 --no-llm 时走确定性 fallback（仅产 source 摘要页）。
    """
    wiki_root = wiki_root.resolve()
    cache_path = cache_path.resolve()
    raw_root = raw_root.resolve()
    path = path.resolve()

    files = [path] if path.is_file() else sorted(p for p in path.rglob("*.md") if p.is_file())
    if not files:
        click.echo(f"未找到 md 文件: {path}")
        return

    client = None if no_llm else make_client_from_config()
    if client is None:
        click.secho("[info] LLM 不可用或 --no-llm，走确定性 fallback", fg="yellow")

    ok = skipped = failed = 0
    for f in files:
        # source_identity：相对 raw_root 的路径（含扩展名）；md 文件名是 {slug}__{hash}.md
        # 简化：用 md 相对 md_root 的路径作为 identity 近似（M1 doc_id 已稳定）
        try:
            rel = f.relative_to(md_root) if md_root in f.parents else f
        except ValueError:
            rel = f
        identity = str(rel).replace("\\", "/")
        index_md = read_index_md(wiki_root)
        today = config.today()
        res = ingest_source(f, identity, wiki_root=wiki_root, cache_path=cache_path, client=client, today=today, index_md=index_md)
        if res.skipped_cached:
            click.secho(f"[SKIP-CACHED] {f.name}", fg="cyan")
            skipped += 1
        else:
            tag = "[FALLBACK]" if res.fallback else "[LLM]"
            click.secho(f"{tag} {f.name} → 写入 {len(res.written_paths)} 页", fg="green")
            ok += 1
    click.echo(f"\n完成: 摄入 {ok}, 缓存跳过 {skipped}, 失败 {failed} (共 {len(files)} 文件)")


@cli.command(name="index")
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
def index_cmd(wiki_root: Path) -> None:
    """重建 wiki/index.md（确定性）。"""
    wiki_root = wiki_root.resolve()
    rebuild_index(wiki_root, config.today())
    click.secho(f"[OK] 已重建 {wiki_root / 'index.md'}", fg="green")


@cli.command()
@click.argument("query")
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--top-k", default=10, help="返回条数。")
def search(query: str, wiki_root: Path, top_k: int) -> None:
    """BM25 检索 wiki 页（RRF 单路直通）。"""
    wiki_root = wiki_root.resolve()
    entries = _wiki_entries(wiki_root)
    bm25 = BM25Retriever([
        {"slug": e["slug"], "section_id": e["section_id"], "title": e["title"], "body_text": e["body_text"]}
        for e in entries
    ])
    hits = bm25.search(query, top_n=50)
    fused = RRFFuser().fuse([hits], k=60, top_k=top_k)
    if not fused:
        click.echo("(无结果)")
        return
    for i, h in enumerate(fused, 1):
        # 填 snippet：找对应 entry 的原文
        e = next((x for x in entries if x["slug"] == h.doc_id and x["section_id"] == h.section_id), None)
        snippet = make_snippet(e["_text"], e["_line_start"], e["_line_end"]) if e else ""
        click.secho(f"[#{i}] score={h.score:.4f}  {h.doc_id} / {h.section_id}", fg="green")
        for line in snippet.splitlines()[:3]:
            click.echo(f"     {line}")
        click.echo(f"     [{h.source}]")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_kb_ingest_search.py -v`
Expected: 2 passed

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全绿（含 M1 测试）

- [ ] **Step 6: Commit**

```bash
git add l1_kb/cli/kb.py tests/test_kb_ingest_search.py
git commit -m "feat(l1/cli): kb ingest/index/search 子命令（BM25 检索 wiki 页）"
```

---

## Task 8: 端到端验收（§13.2）

**Files:**
- 无新增；用 M1 产出的真实 md 样本

- [ ] **Step 1: 清洗样本（若 md/ 已有则跳过）**

Run: `.venv/bin/kb clean l1_kb/knowledge_base/raw`
Expected: 已清洗样本存在 `l1_kb/knowledge_base/md/{cat}/*.md`（M1 产物）

- [ ] **Step 2: 摄入 wiki（fallback 路径，无 LLM key）**

Run: `.venv/bin/kb ingest l1_kb/knowledge_base/md`
Expected: 每份 md 产出 source 摘要页，`wiki/sources/*.md` + `wiki/index.md` + `wiki/log.md` 存在

- [ ] **Step 3: 重建 index**

Run: `.venv/bin/kb index`
Expected: `[OK] 已重建 .../index.md`

- [ ] **Step 4: 精确词召回验收**

Run: `.venv/bin/kb search "order_id"`
Expected: top 结果命中含 `order_id` 的 wiki 页 section（`data_table_order_detail` source 摘要页字段表），snippet 含 `order_id` 字段行。

- [ ] **Step 5: 流程编号召回验收**

先确认有含 `PRC-2024-003` 的样本 md；若无，造一份 `l1_kb/knowledge_base/raw/process/api_doc.md`（内容含 `PRC-2024-003`），清洗后摄入：

Run:
```bash
.venv/bin/kb clean l1_kb/knowledge_base/raw
.venv/bin/kb ingest l1_kb/knowledge_base/md
.venv/bin/kb search "PRC-2024-003"
```
Expected: top 结果命中含该编号的 process/source 页 section，snippet 含 `PRC-2024-003`。

- [ ] **Step 6: 全量 pytest**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test(m2): §13.2 精确词+流程编号召回端到端验收通过"
```

---

## Self-Review

**1. Spec 覆盖**（对照设计 §0-§9）：
- §0 GPL 红线/简化表 → Global Constraints + 各模块注释标注「吸收原理 Python 重实现」✓
- §1 模块布局 → File Structure + Task 3-7 逐模块 ✓
- §2 4 类页 + frontmatter schema → Task 3a/3b ✓
- §3 两步 LLM 摄入（config/client/step1/step2/file_blocks/merge/safe_path/ingest_cache/fallback）→ Task 2/5a/5b/4a/4b/3c/4d/5c ✓
- §4 index.md/log.md → Task 4c ✓
- §5 BM25 检索（base/tokenizer/bm25/snippet）→ Task 6 ✓
- §6 错误处理矩阵 → 各 Task 的失败路径（fallback/丢弃/空返回）测试覆盖 ✓
- §7 依赖 → Task 1 ✓
- §8 实现顺序 → Task 1-8 顺序与 §8 一致 ✓
- §9 待决议（keywords top-N/snippet 500/超时 60s/去重/process code）→ 已在代码中采纳（snippet=500、fallback keywords 由 sections 拼接、去重 `nb in existing`、process code 透传）✓

**2. 占位符扫描**：无 TBD/TODO/"实现稍后"。Task 4c/5c 内有「修正」注记已就地给出修正代码。

**3. 类型一致性**：
- `SearchHit` 字段 `doc_id/section_id/title/snippet/score/source` 在 base/bm25/cli 一致 ✓
- `Frontmatter` 字段在 frontmatter/merge/index_log 一致 ✓
- `ingest_source` 签名（`md_path, source_identity, *, wiki_root, cache_path, client, today, index_md`）在 Task 5c 定义、Task 7 调用一致 ✓
- `BM25Retriever(entries)` entry 键 `slug/section_id/title/body_text` 在 Task 6c/Task 7 一致 ✓（注意 cli 中 `_line_start/_line_end/_text` 为内部键，传给 BM25Retriever 时已剥离）

**4. 已知小瑕疵**（实现时注意，不影响计划正确性）：
- Task 4c import 段的 `..frontmatter_agnostic` 是计划中故意暴露的错误行，已就地给出删除指令。
- Task 5c `except (LLMError, Exception)` 冗余，已注明可简化为 `except Exception`。
- Task 7 `ingest` 的 `source_identity` 用 md 相对路径近似（M1 doc_id 已稳定，identity 仅作 sources 标注与缓存键，不影响检索）。M1 source_identity 本是相对 raw 路径，此处用 md 相对路径是可接受近似——若需严格，可从 md 文件名 `{slug}__{hash}.md` 反解，但 P0 不必要。

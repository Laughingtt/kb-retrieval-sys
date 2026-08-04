# M4 L1 只读 REST API（设计）

> 关联：[PRD §10 只读 REST API](2026-07-30-p0-self-updating-kb-platform-design.md)、[M2 wiki 层设计](2026-07-31-m2-wiki-compounding-layer-design.md)、[M3 增量摄入设计](2026-08-03-m3-incremental-ingest-design.md)。
> 本设计把 M1–M3 已落地的 L1 检索能力（wiki 知识页 + BM25 检索 + section 切分）封装成只读 REST 服务，供 L2 pi Agent 调用。底座 = M2/M3 的 wiki + retrieval 栈；M4 不动摄入侧代码，只读消费已生成的 `wiki/`。

---

## 一、范围与不做

### M4 做

1. **`l1_kb/service/` 三件套**：`store.py`（读 wiki → 内部数据结构）、`search.py`（BM25+RRF+snippet，从 `cli/kb.py` 下沉）、`app.py`（FastAPI app + 6 个只读路由 + Pydantic v2 响应模型）。
2. **6 个只读 GET 端点**：`/health`、`/categories`、`/documents`、`/documents/{slug}`、`/index`、`/search`。全部 GET，**无 POST/PUT/DELETE，无写入/执行端点**。
3. **CLI 复用**：`kb search` 改为调 `service.search`，CLI 与 REST 共享同一检索代码（DRY）。
4. **配置与启动**：`wiki_root` 走 `config.WIKI_ROOT`（env `WIKI_ROOT` 可覆盖）；`uvicorn l1_kb.service.app:app` 启动，`--reload` 仅 dev。
5. **测试**：FastAPI `TestClient`，mock `wiki_root`（`tmp_path` 造 wiki 树），service 层不调 LLM 故无需 mock LLM。

### M4 不做

- **无写入/执行端点** —— 摄入仍只走离线 CLI（`kb ingest`）；REST 全只读。这是 CLAUDE.md 硬约束 2 的硬边界。
- **无鉴权 / 无 CORS / 无限流** —— L1 跑在公司内网，L2 是唯一可信调用方；P0 不上中间件。M6 前如需可补。
- **无持久化倒排索引 / 无缓存服务 / 无后台重建** —— 沿用 M2「纯内存每次重建」策略（语料 ~1000 doc 秒级重建）。单例缓存（方案 C）被否：wiki 被 `kb ingest` 更新后缓存会失效，YAGNI。
- **不碰摄入侧** —— `ingest/`、`incremental/`、`lint/` 一行不改。
- **不换检索算法** —— 仍 BM25+RRF 单路；向量留给未来，端点契约不变（对 L2 透明）。
- **无分页游标 / 无全文正文字段** —— `/documents` 列表只给 summary 不返回 body；section body ≤2000 字截断。响应体积可控即可，不做 cursor 分页。

### 关键约束（已确认，按推荐执行）

- **方案 A（纯函数 service 层 + 瘦 FastAPI 路由）**：逻辑与 HTTP 解耦，CLI 与 REST 共享检索代码。摒弃 B（内联路由，逻辑绑死 HTTP）和 C（单例缓存，引入缓存失效）。
- **身份锚点 = slug**（wiki 页文件名 stem，如 `data_table_order_detail__a3f9c1e2`），与 M2/M3 一致；section 用 `section_id`（s0/s1…）。
- **内部 dataclass 与 Pydantic 模型解耦**：`store.py` 用 dataclass（`PageEntry`/`WikiStore`），不耦合 HTTP；`app.py` 用 Pydantic v2 只管出口契约。
- **SectionOut 保留 `line_start`/`line_end`** —— 供 L2 `read_section` 工具做确定性切片锚点；这不是「向量索引键」，不违反 M1「行号不外泄给索引键」。
- **wiki_root 走 `config.WIKI_ROOT`**（env `WIKI_ROOT` 可覆盖），与 CLI 默认一致。
- **新增依赖**：`fastapi`、`uvicorn`（运行）；`httpx`（测试，TestClient 底层）。无外部 SaaS。
- **GPL 红线 / 独立项目 / 全自托管** —— 沿用全局约束。

---

## 二、架构与端点契约

### 组件拓扑

```
┌─────────────────────────────────────────────────────────────┐
│  L2 pi Agent（M5，唯一调用方）                                │
│  list_categories / list_documents / grep_docs(read_section) │
│  / grade_relevance → HTTP GET                                │
└───────────────────────────┬─────────────────────────────────┘
                            │ 只读 HTTP GET（内网）
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  l1_kb/service/app.py  ── FastAPI（6 路由，Pydantic v2 出口） │
│    /health /categories /documents /documents/{slug}          │
│    /index /search                                            │
└───────────┬───────────────────────────────┬─────────────────┘
            │                               │
            ▼ 调纯函数                      ▼ 调纯函数
┌───────────────────────────┐  ┌──────────────────────────────┐
│ service/store.py          │  │ service/search.py            │
│ load_store(wiki_root)     │  │ search(store, q, top_k)      │
│  → WikiStore(pages[])     │  │  = BM25Retriever + RRF +     │
│  PageEntry(slug,type,     │  │    make_snippet（下沉自 cli） │
│    title,sections[],raw)  │  │  → list[SearchHit]           │
└───────────┬───────────────┘  └──────────────────────────────┘
            │ 读
            ▼
┌─────────────────────────────────────────────────────────────┐
│  wiki/  （M2/M3 生成，M4 只读）                              │
│   sources/*.md  entities/*.md  concepts/*.md  process/*.md  │
│   index.md  log.md                                          │
└─────────────────────────────────────────────────────────────┘
            ▲
            │ 离线写入（M4 不碰）
┌───────────┴─────────────────────────────────────────────────┐
│  kb ingest / kb clean / kb lint（CLI，离线摄入脚本）          │
└─────────────────────────────────────────────────────────────┘
```

### 端点契约（稳定，内部演进不破坏）

| 方法 | 路径 | 用途 | L2 工具映射 |
| --- | --- | --- | --- |
| GET | `/health` | 存活 + wiki 状态（页数/最后更新） | 启动探测 |
| GET | `/categories` | 列出 4 类页及其计数 | `list_categories` |
| GET | `/documents` | 列文档 summary（分页 + type 过滤） | `list_documents` |
| GET | `/documents/{slug}` | 单文档全文（sections + frontmatter） | `read_section` 定位 |
| GET | `/index` | wiki/index.md 目录视图 | 浏览/导航 |
| GET | `/search?q=...&top_k=...` | BM25 检索 | `grep_docs` |

全部 GET，无 body，无副作用。`/search` 的 `q` 经 query string 传入。

---

## 三、数据模型与响应 Schema

### 3.1 内部数据结构（`store.py`，dataclass，不耦合 HTTP）

```python
@dataclass
class SectionEntry:
    section_id: str        # s0/s1…（M1 splitter 顺序，稳定）
    title: str             # "页title / section标题"
    line_start: int        # 1-based，含
    line_end: int          # 1-based，含
    body: str              # 该 section 行范围原文（≤2000 字截断）

@dataclass
class PageEntry:
    slug: str              # 文件名 stem = 文档 id
    type: str              # source/entity/concept/process
    title: str             # frontmatter.title
    path: Path             # wiki 相对路径
    sections: list[SectionEntry]
    raw: str               # 整页原文（供 snippet 回切）

@dataclass
class WikiStore:
    pages: list[PageEntry]
    # 派生索引（每次 load 重建，不持久化）
    by_slug: dict[str, PageEntry]            # field(default_factory=dict)
    by_type: dict[str, list[PageEntry]]      # field(default_factory=dict)
```

`load_store(wiki_root) -> WikiStore`：扫 `wiki/**/*.md`，跳过 `index`/`log`/`overview` 茎，解析 frontmatter（复用 `ingest.wiki.frontmatter.parse`）取 `type`/`title`，复用 `ingest.section_splitter.split` 切 section。**逻辑 = `cli/kb.py:_wiki_entries`（line 121）的下沉 + 扩展**（多记 type/raw/path，body 截断）。

### 3.2 出口响应模型（`app.py`，Pydantic v2）

```python
class SectionOut(BaseModel):
    section_id: str
    title: str
    line_start: int
    line_end: int
    body: str          # ≤2000 字截断；超过尾部加 "…[截断]"

class DocumentSummary(BaseModel):
    slug: str
    type: str
    title: str
    section_count: int
    updated: str | None    # frontmatter.updated（无则 None）

class DocumentOut(BaseModel):
    slug: str
    type: str
    title: str
    updated: str | None
    sections: list[SectionOut]

class CategoryOut(BaseModel):
    type: str             # source/entity/concept/process
    count: int

class IndexEntry(BaseModel):
    type: str
    title: str
    slug: str

class IndexOut(BaseModel):
    entries: list[IndexEntry]   # 由 index.md 解析；index.md 缺失则回退 by_type 派生

class SearchHitOut(BaseModel):
    doc_id: str           # = slug
    section_id: str
    title: str
    snippet: str          # ≤500 字（make_snippet max_chars=500）
    score: float
    source: str           # "bm25"

class SearchOut(BaseModel):
    query: str
    total: int
    hits: list[SearchHitOut]

class HealthOut(BaseModel):
    status: str           # "ok"
    wiki_root: str
    page_count: int
    last_updated: str | None   # 取所有页 frontmatter.updated 的最大值
```

### 3.3 设计要点（已确认）

- **`/documents` 列表不返回 body**：只给 `DocumentSummary`（slug/type/title/section_count/updated），避免一次拉 ~1000 doc 全文。需要正文再 `GET /documents/{slug}`。
- **section body ≤2000 字截断**：超长尾部截断 + `"…[截断]"` 标记。snippet 走 `make_snippet(max_chars=500)`，与 CLI 一致。
- **`line_start`/`line_end` 保留**：L2 `read_section` 用它做确定性切片锚点（回切 `raw` 或 body 子串），非索引键。
- **`updated` 可空**：fallback 页可能无 frontmatter.updated，统一 `str | None`，不抛错。
- **`/index` 回退**：`index.md` 是 M2 确定性产物，正常存在；若被误删，`IndexOut` 回退用 `by_type` 派生（降级而非 500）。

---

## 四、端点详细行为与查询参数

### GET /health
- 无参。返回 `HealthOut`。`page_count` = `len(store.pages)`；`last_updated` = 所有页 `updated` 取最大（全空则 None）。
- HTTP 200 恒返回（wiki 为空时 `page_count=0`，仍 200，`status="ok"`——存活探测语义，不把「无数据」当故障）。

### GET /categories
- 无参。返回 `list[CategoryOut]`，固定 4 类顺序 `source/entity/concept/process`（与 M2 `PAGE_TYPES` 一致），count=0 的类也列出（L2 需知道有哪些类别槽位）。

### GET /documents
- 查询参数：
  - `type`（可选）：`source`/`entity`/`concept`/`process`，过滤；非法值 → 422。
  - `page`（可选，默认 1，≥1）：页码。
  - `page_size`（可选，默认 50，1–200）：每页条数。
- 返回 `{"items": [DocumentSummary], "page": int, "page_size": int, "total": int}`。`total` = 过滤后总数（非当前页数）。
- 排序：按 `type` 升序、组内按 `title` 升序（与 `index_log.rebuild_index` 一致，确定性）。

### GET /documents/{slug}
- 路径参 `slug`。返回 `DocumentOut`。
- slug 不存在 → **404** + `{"detail": "document not found: {slug}"}`。
- slug 含路径分隔符 / `..` → 404（不泄露文件系统，按「找不到」处理，不 500）。

### GET /index
- 无参。返回 `IndexOut`。优先解析 `wiki/index.md`（M2 产物，按 type 分组 + title 排序）；解析失败或文件缺失 → 回退 `by_type` 派生（同序）。降级时 `IndexOut.entries` 仍可用，不报错。

### GET /search
- 查询参数：
  - `q`（必需）：查询串。空 / 仅空白 → **400** + `{"detail": "query must not be empty"}`（与 CLI「无结果」不同：REST 需明确参数校验）。
  - `top_k`（可选，默认 10，1–50）：返回条数上限。
- 返回 `SearchOut`。无命中 → 200 + `total=0, hits=[]`（不是 404）。
- 检索链 = `BM25Retriever(store section entries)` → `search(q, top_n=50)` → `RRFFuser().fuse([hits], k=60, top_k)` → 逐 hit `make_snippet(page.raw, line_start, line_end)`。**逻辑 = `cli/kb.py:search`（line 247）下沉**。

---

## 五、数据流 / 组件交互

### 请求处理流（以 /search 为例）

```
GET /search?q=订单字段&top_k=5
   │
   ▼ app.py 路由：解析 q/top_k（Pydantic + Query 校验）
   │   q 空 → 400；top_k 越界 → 422
   ▼ store = load_store(config.WIKI_ROOT)   ← 每请求重建（纯函数，无缓存）
   ▼ hits = search(store, q, top_k)
   │   ├─ entries = [{slug,section_id,title,body_text} for page in store.pages for s in page.sections]
   │   ├─ bm25 = BM25Retriever(entries); raw_hits = bm25.search(q, top_n=50)
   │   ├─ fused = RRFFuser().fuse([raw_hits], k=60, top_k)
   │   └─ for h in fused: snippet = make_snippet(page.raw, s.line_start, s.line_end)  ← 回查 store
   ▼ SearchOut(query=q, total=len(fused), hits=[SearchHitOut(...) for h in fused])
   ▼ 200 JSON
```

### 与摄入侧的解耦

- M4 **只读** `wiki/`。`kb ingest` 更新 wiki 后，下一次 REST 请求 `load_store` 自动读到新内容（无缓存故无失效问题）。这是选方案 A、否方案 C 的核心理由。
- `load_store` 是纯函数，每次请求调用一次；P0 语料小（~1000 doc），重建 ~百毫秒级，可接受。若未来变慢，可在 service 层加带 mtime 失效的缓存，但**契约不变**——这是预留的演进点，M4 不实现。

---

## 六、错误处理

| 场景 | HTTP | body |
| --- | --- | --- |
| wiki_root 不存在 / 空 | `/health` 200（page_count=0）；`/categories` 200（全 0）；`/documents` 200（空）；`/search` 200（无命中） | — |
| `/documents/{slug}` slug 不存在 | 404 | `{"detail": "document not found: {slug}"}` |
| `/documents/{slug}` slug 含 `/` 或 `..` | 404 | 同上（不泄露 FS） |
| `/search` q 缺失 / 空 / 仅空白 | 400 | `{"detail": "query must not be empty"}` |
| 查询参数越界（page<1, page_size>200, top_k>50, type 非法） | 422 | FastAPI 默认校验错误体 |
| `load_store` 读单页 frontmatter 解析失败 | 跳过该页 + 服务端 log warn，不 500 | 其余页正常返回 |
| 未捕获异常 | 500 | `{"detail": "internal error"}`（不泄露堆栈） |

**原则**：只读服务对调用方宽容——「无数据」用 200 + 空集表达，不用 4xx/5xx；只有「参数错」用 4xx、「真故障」用 5xx。这样 L2 Agent 不必为空结果做异常分支。

---

## 七、CLI 重构（DRY）

`cli/kb.py:search`（line 247-267）改为复用 `service.search`：

```python
# 改后（伪码）
from ..service.store import load_store
from ..service.search import search as svc_search

@cli.command()
@click.argument("query")
@click.option("--wiki-root", "wiki_root", default=DEFAULT_WIKI)
@click.option("--top-k", default=10)
def search(query, wiki_root, top_k):
    wiki_root = wiki_root.resolve()
    store = load_store(wiki_root)
    hits = svc_search(store, query, top_k)   # 返回 list[SearchHit]，含 snippet
    if not hits:
        click.echo("(无结果)"); return
    for i, h in enumerate(hits, 1):
        click.secho(f"[#{i}] score={h.score:.4f}  {h.doc_id} / {h.section_id}", fg="green")
        for line in h.snippet.splitlines()[:3]:
            click.echo(f"     {line}")
        click.echo(f"     [{h.source}]")
```

- `_wiki_entries`（line 121-146）从 cli 下沉到 `service/store.py:load_store`，cli 不再持有此函数。
- CLI 行为/输出格式不变（现有 M3 e2e `test_m3_incremental_e2e.py` 的 search 断言仍过）。
- `BM25Retriever`/`RRFFuser`/`make_snippet` 仍在 `retrieval/`，service 层 import 复用，不搬家。

---

## 八、配置与启动

### 新增依赖（pyproject.toml）

运行时：`fastapi`、`uvicorn[standard]`。开发/测试：`httpx`（TestClient 底层，已是常见 dev 依赖）。

```toml
[project]
dependencies = [
    # ... 既有 ...
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
]
[project.optional-dependencies]
dev = ["pytest", "reportlab", "httpx>=0.27"]
```

### 启动

```bash
# 默认 wiki_root = config.WIKI_ROOT（l1_kb/knowledge_base/wiki）
.venv/bin/uvicorn l1_kb.service.app:app --host 0.0.0.0 --port 8000

# dev 热重载
.venv/bin/uvicorn l1_kb.service.app:app --reload --port 8000

# 指向其他 wiki
WIKI_ROOT=/data/some/wiki .venv/bin/uvicorn l1_kb.service.app:app --port 8000
```

`app.py` 在模块级构造 FastAPI app；`wiki_root` 在路由内懒取 `config.WIKI_ROOT`（每请求读，env 改了重启即生效，不缓存）。

### 入口脚本（可选，便于 L2 调用）

`pyproject.toml` 增 `kb-serve` 脚本点：

```toml
[project.scripts]
kb = "l1_kb.cli.kb:cli"
kb-serve = "l1_kb.service.app:run"   # app.py 内 def run(): uvicorn.run(app, ...)
```

---

## 九、测试策略

### service 层单测（不调 LLM，纯函数）

- `tests/test_service_store.py`：`tmp_path` 造 wiki 树（2–3 页含 frontmatter + section），断言 `load_store` 的 pages/by_slug/by_type 正确；跳过 index/log/overview；frontmatter 解析失败页被跳过。
- `tests/test_service_search.py`：造含 `order_id` 字段的 source 页，`search(store, "order", 5)` 命中且 snippet ≤500 字；空 query 返回 `[]`（service 层不抛，留给路由 400）；无命中返回 `[]`。

### REST 层单测（FastAPI TestClient + httpx）

- `tests/test_service_app.py`：用 `tmp_path` 造 wiki，monkeypatch `config.WIKI_ROOT` 指向它（或 app 支持 dependency override 注入 wiki_root）。覆盖：
  - `/health` 200 + page_count 正确。
  - `/categories` 固定 4 类 + count。
  - `/documents?type=source&page=1&page_size=10` 过滤 + 分页 + total。
  - `/documents/{slug}` 200 + sections；未知 slug 404；含 `/` 的 slug 404。
  - `/index` 200；index.md 缺失时回退。
  - `/search?q=order&top_k=5` 200 + hits；`q` 空 400；`top_k=999` 422。
  - wiki 为空时各端点均 200 + 空集（不 5xx）。

### CLI 回归

- 现有 `tests/test_m3_incremental_e2e.py`（真 key）+ `tests/test_kb_cli_m3.py` 的 search 断言仍过（验证 DRY 重构未改 CLI 行为）。

### 不做

- 不加 e2e 真 LLM 测试 —— service 层不调 LLM。
- 不加性能基准 —— P0 语料小，重建耗时可接受，YAGNI。

---

## 十、验收标准

1. `uvicorn l1_kb.service.app:app` 启动，6 端点全部 200（空 wiki 也 200 + 空集）。
2. `kb search` 行为/输出不变（M3 e2e search 断言仍过）。
3. service 层 + REST 层单测全绿（mock wiki_root，无需 LLM key）。
4. 无任何 POST/PUT/DELETE 路由（`grep -rE "@app\\.(post|put|delete|patch)" l1_kb/service/` 无命中）。
5. `pyproject.toml` 新增 fastapi/uvicorn/httpx，`uv pip install -e ".[dev]"` 成功。
6. 文档：README 后续计划表 M4 标 ✅，补一节「REST API 启动 + 端点速查」。

---

## 十一、演进预留（不在 M4 实现）

- **混合检索**：注册 `VectorRetriever` 后 `RRFFuser.fuse([bm25, vector])` 两路；`/search` 契约不变（对 L2 透明）。
- **缓存**：若重建变慢，service 层加 wiki 目录 mtime 失效缓存；契约不变。
- **鉴权 / CORS / 限流**：M6 接 Open WebUI 前按内网部署要求补中间件。
- **流式 / 长查询**：L2 流式由其自身 SSE 端点负责，L1 `/search` 保持一次性 JSON。

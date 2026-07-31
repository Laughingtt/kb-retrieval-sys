# M2 设计：index.json 生成 + BM25 单路检索

> 本文是 P0 PRD（`docs/superpowers/specs/2026-07-30-p0-self-updating-kb-platform-design.md`）§16 里程碑 **M2** 的实现设计。M1（清洗 pipeline → md/ + sections）已完成并提交（`c9784ca`）。M2 在 M1 产出的 `md/` 上构建两条并行输出线，兑现 PRD §7.2。

## Context（为什么做这个）

PRD §16 M2 验收标准：**`kb search` 精确词召回用例通过**（§13.2 精确词 + 流程编号两类）。M2 把"清洗产物"变成"可检索知识库"——给每份文档生成检索卡片（index.json，LLM 两步归纳），并建 BM25 关键词倒排（section 级），让 `kb search "order_id"` / `"PRC-2024-003"` 能精确命中。

**M2 不做**（明确 fence）：hash.json 变更检测 / 增量摄入 / lint / rebuild / 只读 REST API / 向量索引（均属 M3/M4）。向量环境 P0 不装，§8.4 单路 BM25 + RRF 单路直通。

**已确认决策**：
- LLM = DeepSeek（OpenAI 兼容端点，env 配置，model `deepseek-chat`）；不可用时优雅降级，不阻塞 BM25 验收。
- BM25 = `rank-bm25`（BM25Okapi）+ jieba + CJK bigram（F7）；倒排文档单元 = section 标题 + 正文；纯内存每次重建。
- 范围 = 最小 M2。

**环境**：Python 3.12.3 + `uv` 0.11.32；系统 site-packages 不可写 → 用 venv。`jieba` / `rank-bm25` / `openai` 需装（用清华镜像 `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`）。

---

## 一、架构与模块布局

M2 在 M1 的 `md/{cat}/{doc_id}.md` 上构建两条并行输出线，严格对齐 PRD §7.2 的 (A) 元数据线 + (B) 检索索引线：

```
md/{cat}/{doc_id}.md  ──┬── (A) 元数据线 ──▶ index.json
                        │     IndexBuilder (LLM 两步: 分析→生成)
                        │     行号回填复用 M1 SectionSplitter（确定性强）
                        │
                        └── (B) 检索索引线 ──▶ BM25 (内存) + RRF (单路直通)
                              BM25Retriever (jieba+bigram F7, over section title+body)
                              Retriever/RRFFuser (§8.1 接口, P0 仅 BM25 路注册)
```

**新增模块（`l1_kb/` 下）**：

```
l1_kb/
├── llm/                          # 新增
│   ├── __init__.py
│   ├── client.py                 # OpenAI 兼容客户端: 读 env(DEEPSEEK_*/可覆盖), chat_json()
│   └── summarize.py              # 两步归纳: step1_analyze()→{category,entities,related_docs}
│                                 #             step2_generate()→{title,summary,keywords}
├── index/                        # 新增
│   ├── __init__.py
│   ├── builder.py                # IndexBuilder: 跑遍 md/, LLM 两步 + 行号回填 → index.json
│   └── store.py                  # index.json 读写 (按 doc_id upsert; M2 全量重建为主)
├── retrieval/                    # 新增
│   ├── __init__.py
│   ├── tokenizer.py              # jieba + CJK bigram (F7) → 词项集合
│   ├── bm25.py                   # BM25Retriever(Retriever): 建/查倒排, source='bm25'
│   ├── base.py                   # Retriever ABC + SearchHit dataclass + RRFFuser
│   └── snippet.py                # 按 line_start/end 从 md 切 snippet
├── config.py                     # 新增: 集中读 env (raw/md/index 路径 + LLM 配置)
└── cli/kb.py                     # 扩展: + kb index / kb search
```

**边界守卫**：以上全部是**离线摄入脚本**（写 `index.json`）与**只读 CLI 检索**，无任何 Agent 操作工具——CLAUDE.md 硬约束 ②（L2 Agent 工具只读）不受影响。L1 摄入脚本写 index.json 属正常生成物，非 Agent action tool。

---

## 二、LLM 两步归纳（`l1_kb/llm/`）

对齐 PRD §7.2.3。OpenAI 兼容客户端，默认 DeepSeek。

### 2.1 `config.py`（集中读 env）

- `RAW_ROOT` / `MD_ROOT` / `INDEX_PATH`（默认在 `l1_kb/knowledge_base/` 下）
- `LLM_BASE_URL`（默认 `https://api.deepseek.com/v1`）、`LLM_API_KEY`（从 `DEEPSEEK_API_KEY` 读）、`LLM_MODEL`（默认 `deepseek-chat`）
- 全部可被 env 覆盖，公司内部 OpenAI 兼容端点（CLAUDE.md ③）日后直接换 env 即可，不改代码。

### 2.2 `client.py` — OpenAI 兼容薄封装

- `chat_json(system, user) -> dict`：调 chat completions，`response_format={"type":"json_object"}`，解析 JSON；非法 JSON 重试一次；仍失败抛 `LLMError`（由上层降级捕获）。无流式、无工具——纯结构化 JSON 进出。

### 2.3 `summarize.py` — 两步（F5 长文档分块推到 M3；M2 文档均小）

```python
def step1_analyze(client, md_text, section_titles) -> dict:
    """→ {category: data_product|process|data_table, entities: [], related_docs: []}"""
    # category 必须落在三个枚举值; related_docs 给候选 doc_id(可空)

def step2_generate(client, step1_result, section_titles) -> dict:
    """→ {title, summary(3-5句), keywords[3-8]}"""

def summarize_doc(md_text, sections) -> dict:
    """合并两步 → index.json 单文档条目的 LLM 字段"""
```

Prompt 结构 = PRD §7.2.3 原文（编目员 system prompt，JSON-only，category∈枚举，summary 点到为止，keywords 含字段名/编号）。

### 2.4 `related_docs` 在 M2 的处理

LLM 在 minimal M2 里只看当前文档（不注入全局目录），候选多为空或幻觉 doc_id。**交叉验证**：对返回的候选与本次实际建索引的 `doc_id` 集合比对，丢弃不匹配的。保持 index.json 诚实；真正的跨文档关联（§9.2.1 双向回填）是 M3 增量工作。

### 2.5 优雅降级

`LLM_API_KEY` 未设或调用失败（重试后仍失败）时，`summarize_doc` 走确定性回退：title ← 首个 `#` 标题、summary ← 首个非标题段落、keywords ← tokenizer 高频 token top-N、category ← raw 子目录（同 M1 `_derive_category`），并给条目打 `meta.llm_source = "fallback"`。这保证 `kb index` 即使无网络也总能产出可用 index.json——BM25 与 §13.2 验收从不依赖 LLM 字段。

---

## 三、index.json 生成（`l1_kb/index/`）

### 3.1 `store.py` — 读写 index.json

- `load() -> IndexDoc` / `save(IndexDoc)`，schema 按 PRD §7：

```json
{
  "version": "1.0",
  "indexed_at": "ISO8601",
  "documents": [{ "doc_id", "title", "category", "source_path", "md_path",
                  "summary", "keywords", "ingested_at", "sections[]", "related_docs[]",
                  "meta": {"llm_source"} }]
}
```

- `upsert(doc_entry)`：按 `doc_id`（存在则覆盖，不存在则 append）。M2 以全量重建为主，但 upsert 为 M3 增量留门。

### 3.2 `builder.py` — `IndexBuilder.build()`

```
扫描 raw/ 一次 → {doc_id → source_path} 映射（复用 M1 make_doc_id）
for each md/{cat}/{doc_id}.md:
  1. doc_id        ← 从文件名解析（已是 {slug}__{hash}.md）
  2. md_text       ← read file
  3. sections      ← M1 SectionSplitter.split(md_text)   # 行号回填复用,确定性强
  4. llm_fields    ← summarize_doc(md_text, sections)    # 两步 / 回退
  5. related_docs  ← 交叉验证过滤（只留真实 doc_id）
  6. source_path   ← 从 {doc_id→source_path} 映射取
  7. md_path       ← 直接已知（md/{cat}/{doc_id}.md）
  8. assemble entry → upsert
write index.json
```

### 3.3 source_path 反推

M1 的 `doc_id = slug(raw相对路径)__sha256[:8]`。为回填 `source_path` 而不在 M1 存它，`builder` 开头扫 `raw/` 一次，算每个文件的 doc_id，建 `{doc_id → source_path}` 映射——复用 M1 `make_doc_id`，无新哈希逻辑。

### 3.4 sections 字段子集

index.json 的 `sections[]` 只存元数据子集 `{section_id, title, line_start, line_end, level}`——**不含 `is_table`**（那是 M1 splitter 内部关注，PRD §7 schema 未含）。组装时剥离。

### 3.5 确定性说明

`indexed_at` / `ingested_at` 是时间戳——使 `index.json` 跨运行非字节稳定，这是预期的（它是缓存，非真相源）。测试只断言结构，不断言这两个字段。

---

## 四、BM25 检索（`l1_kb/retrieval/`）

> **通俗讲**：本节把 §8 的"检索底座"落到 M2 可实现的具体类与签名。P0 只有 BM25 一路，RRF 单路直通——但接口与融合器都按两路设计摆好，向量路将来注册即可，不改契约。

### 4.1 接口层 `base.py`（Retriever ABC + SearchHit + RRFFuser）

兑现 §8.1 与 §8.4：检索机制对 L2 透明、内部可演进、契约不变。

```python
# l1_kb/retrieval/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SearchHit:
    doc_id: str            # 如 data_table_order_detail__a3f9c1e2
    section_id: str        # s0, s1, ...（与 section_splitter 一致）
    title: str             # section 标题
    snippet: str           # 按 line_start/end 切出的原文片段
    score: float           # 融合后 RRF 分数
    source: str            # 'bm25' | 'vector'

class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, top_n: int = 50) -> list[SearchHit]:
        """返回 section 级候选；source 标注来源路。"""

class RRFFuser:
    def fuse(self, results: list[list[SearchHit]], k: int = 60,
             top_k: int = 10) -> list[SearchHit]:
        """RRF: score = Σ 1/(k + rank_i)；section 级去重(同 (doc_id,section_id) 取最高分)；
        截断 top_k。单路时为直通（rank_i 只有一路，去重+排序不变）。"""
```

> **单路直通说明**：P0 只注册 BM25Retriever，`fuse([bm25_results])` 仅去重+按单路 rank 重排，等价 passthrough。保留 fuser 在路径中，是为向量化后只需 `register(VectorRetriever)` 即变两路，**§8.4 契约与 `/search` 外部行为不变**。VectorRetriever 在 M2 仅以"注册即生效"契约预留，不实现。

### 4.2 分词 `tokenizer.py`（jieba + CJK bigram，F7）

词项构造 = **jieba 切词 ∪ 连续 CJK 串的 2-gram**。jieba 对未登录词（`order_status`、`PRC-2024-003`）切不准时，bigram 兜底命中。

```python
# l1_kb/retrieval/tokenizer.py
import re
import jieba

_CJK_RE = re.compile(r"[一-鿿]+")

def tokenize(text: str) -> list[str]:
    """返回去重后的词项列表：jieba 切词 ∪ CJK bigram。"""
    tokens: set[str] = set(jieba.cut_for_search(text))
    for run in _CJK_RE.findall(text):
        for i in range(len(run) - 1):
            tokens.add(run[i:i + 2])  # "订单状态" → 订单/单状/状态
    return [t for t in tokens if t.strip()]
```

> query 与 section 文本走同一 `tokenize`，保证倒排表词项空间与查询词项一致。

### 4.3 BM25 检索器 `bm25.py`

文档单元文本 = section 标题 + 正文。IDF 全库统计（rank-bm25 `BM25Okapi` 内部完成）。**纯内存，每次运行重建**（M2 不持久化倒排文件）。

```python
# l1_kb/retrieval/bm25.py
from rank_bm25 import BM25Okapi
from .base import Retriever, SearchHit
from .tokenizer import tokenize

class BM25Retriever(Retriever):
    def __init__(self, entries: list[dict]) -> None:
        """entries: [{doc_id, section_id, title, body_text}]。
        每个 entry tokenizes 成一个 corpus 文档；构造 BM25Okapi。"""
        self._meta = entries
        self._corpus = [tokenize(f"{e['title']} {e['body_text']}") for e in entries]
        self._bm25 = BM25Okapi(self._corpus)  # IDF 全库统计在此完成

    def search(self, query: str, top_n: int = 50) -> list[SearchHit]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_n]
        hits: list[SearchHit] = []
        for idx, sc in ranked:
            if sc <= 0:
                continue
            e = self._meta[idx]
            hits.append(SearchHit(
                doc_id=e["doc_id"], section_id=e["section_id"],
                title=e["title"], snippet="",  # snippet 由调用方后续填
                score=float(sc), source="bm25",
            ))
        return hits
```

### 4.4 片段切分 `snippet.py`

按 section 的 1-based 行号范围从 markdown 原文切片，控制在 `max_chars` 内。

```python
# l1_kb/retrieval/snippet.py
def make_snippet(md_text: str, line_start: int, line_end: int,
                 max_chars: int = 500) -> str:
    """按 1-based 行号范围 [line_start, line_end] 切片，超长尾部截断。"""
    lines = md_text.splitlines()
    seg = lines[line_start - 1:line_end]
    out = "\n".join(seg)
    return out[:max_chars]
```

### 4.5 查询流程 `kb search "order_id"`

```
kb search "order_id"
  → BM25Retriever.search("order_id", top_n=50)        # §4.3，返回 50 条 source='bm25'
  → RRFFuser.fuse([bm25_hits], k=60, top_k=10)        # §4.1，单路直通：去重+截断到 10
  → 对每条 hit：make_snippet(md[doc_id], line_start, line_end)  # §4.4
  → 按 §11.2 格式打印
```

输出遵循 §11.2：

```
[#1] score=0.0312  data_table_order_detail__a3f9c1e2 / s0
     Sheet1: 订单主表
     | order_id | string | 订单唯一标识 |
     [md: md/data_table/order_detail.md:1-48]
```

### 4.6 验收对齐（§13.2）

`kb search "order_id"` 与 `kb search "PRC-2024-003"` 为 P0 硬指标：top_5 命中含目标词的 section，snippet 含该字段行。BM25 + CJK bigram 在精确词/编号上的强召回正是这两条用例的验证能力所在；语义召回用例留待向量就绪。

---

## 五、错误处理 + 测试 + 验收

### 5.1 错误处理矩阵

| 场景 | 处理策略 | 结果 |
| --- | --- | --- |
| `LLM_API_KEY` 未设 / LLM 调用失败 | 不抛异常，走确定性 fallback（见 §2.5），`meta.llm_source='fallback'` | 摄入继续，索引可用 |
| LLM 返回非法 JSON | 解析失败重试一次；仍失败则降级为 fallback | 同上 |
| BM25 空查询 / 空语料 | 直接返回 `[]`，不构造索引 | 不崩 |
| 源 md 文件缺失 | 跳过该 doc 并 `warn`，继续处理其余 | 部分成功 |
| pandoc/清洗异常 | M1 已兜底，本层不再处理 | — |

> 设计原则：摄入侧容错降级，查询侧纯本地不依赖 LLM，故 LLM 不可用不影响检索。

### 5.2 测试策略

**单元测试**（`tests/`，pytest，沿用 `conftest.py` 的 `FIXTURES`/`RAW`/`make_order_xlsx`/`make_wide_xlsx`/`make_pdf`）：

- **tokenizer F7**：中文走 jieba+CJK bigram、英文按词，断言 `order_id`→`["order_id"]`、`订单状态` 含 `订单/单状/状态` bigram。
- **BM25Retriever**：用固定小语料断言排序正确；top_5 截断；空输入返回 `[]`。
- **RRFFuser**：单路 BM25 时退化为透传不报错；`doc_id` 去重、分数按 1/(k+rank) 累加正确。
- **snippet 切片**：命中词所在行被含入 snippet。
- **IndexBuilder upsert**：同 `doc_id` 二次写入覆盖不重复。
- **summarize 两步**：**必须 mock LLM client**（注入返回固定 JSON 的假 client），断言 title/summary/keywords/category 正确；再断言 `client=None` 时 `llm_source='fallback'` 且字段确定性。**CI 不得要求 `DEEPSEEK_API_KEY`，所有 LLM 路径用 mock。**

**集成测试**：`kb index` 端到端写入合法 `index.json`（schema 校验 + 5 份样本全覆盖）；`kb search "order_id"`/`"PRC-2024-003"` 端到端返回 section 级结果。

### 5.3 §13.2 验收用例映射到真实样本

| 用例 | 命令 | 期望（M2） |
| --- | --- | --- |
| 精确词召回 | `kb search "order_id"` | top_5 命中 `order_detail.xlsx` 的 s0（订单）与 s1（订单明细）两个 section，snippet 含 `order_id` 字段行 |
| 流程编号召回 | `kb search "PRC-2024-003"` | top_5 命中 `api_doc.md` 含该编号的 section |
| 语义召回（订单状态） | — | **本 P0 不要求**，向量就绪后验证（§13.2 第 3 行） |

### 5.4 通过判据

§13.2 精确词 + 流程编号两类用例 top_5 命中正确 section 为 M2 必过项。**LLM-fallback 路径同样须通过这两类**（BM25 只依赖 section 文本，不依赖 LLM 归纳字段）。

### 5.5 验证命令

```bash
pytest tests/ -q                          # 单元 + 集成（无需 API key）
kb index                                  # 对 5 份真实样本建索引
kb search "order_id" && kb search "PRC-2024-003"   # 实跑验收
```

---

## 六、依赖（pyproject.toml 增量）

**运行时新增**：
- `openai`（OpenAI 兼容客户端，调 DeepSeek/公司内部端点）
- `jieba`（中文分词）
- `rank-bm25`（BM25Okapi）

**不进 M2**：`bge-m3` / `sentence-transformers` / `numpy`（向量，M3+）/ `fastapi` / `uvicorn`（REST API，M4）/ `watchdog`（watch，M3）。

安装用清华镜像：`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple UV_HTTP_TIMEOUT=600 uv pip install ...`

---

## 七、实现顺序（写代码时的步骤）

1. `pyproject.toml` 加依赖 + `uv pip install`（openai/jieba/rank-bm25）。
2. `config.py`（最纯，先立基）。
3. `llm/client.py` + `llm/summarize.py` + 单测（mock client，含 fallback 路径）。
4. `retrieval/{base,tokenizer,bm25,snippet}.py` + 单测（F7/排序/RRF/snippet）。
5. `index/{store,builder}.py` + 单测（upsert、source_path 反推）。
6. `cli/kb.py` 扩展 `kb index` / `kb search`。
7. 端到端：`kb index` → `kb search` 跑 §13.2 + pytest 全绿。
8. commit。

---

## 八、待决议（实现中如遇则定，否则按倾向）

- **keywords 回退 top-N**：倾向 top-5 高频 token（去停用词）。
- **snippet max_chars**：倾向 500（§11.2 示例片段约此量级）。
- **LLM 超时**：倾向单步 60s 超时，失败即降级。

# M2 设计：复利 wiki 层（参考 llm_wiki，Python 简化实现）+ BM25 检索

> 本文是 P0 PRD（`docs/superpowers/specs/2026-07-30-p0-self-updating-kb-platform-design.md`）§16 里程碑 **M2** 的**修订设计**。它**取代** `2026-07-31-m2-index-bm25-design.md`（index.json 单路方案）。
>
> **修订动因（用户指令，逐字保留原意）**：「底层 wiki 目录的建设完全可以参考 llm wiki 开源的代码……我们只是用 python 实现它的底层知识建设体系逻辑，不要自己臆想其他方案来弥补；最终检索时我们只会考虑 bm25 和向量检索，但文档的清洗，wiki 复利，关联都参考 llm wiki 的实现，但尽量简化逻辑」。
>
> M1（清洗 pipeline → `md/{cat}/{doc_id}.md` + sections）已完成（`c9784ca`）。M2 在 M1 产物上构建**复利 wiki 层**——LLM 两步摄入把每份原件消化成若干 wiki 页（带 frontmatter），再以确定性方式维护 `index.md`/`log.md`，最终 BM25 直接索引 wiki 页。

---

## 0. 借鉴红线与简化原则（GPL 合规）

**红线（CLAUDE.md 之外本设计新增的硬约束）**：
- llm_wiki 是 GPL v3（Copyright 2024-2026 Yong Su），**不导入、不链接、不复制其源码**；只吸收其公开可见的**工程方法/算法**（不受版权保护），用 Python 重新实现。所有借鉴标注「理解原理后用 Python 重新实现」。
- llm_wiki 的"答案回填进 wiki"（Karpathy 核心思想）是一次**写操作**，与 CLAUDE.md 硬约束 ②（L2 Agent 工具只读）冲突。本设计的所有 wiki 写入（摄入生成、frontmatter 合并、index/log 重建、BM25 建索引）一律是**离线摄入脚本**的操作，**不是 Agent 工具**；查询期答案回填留待 P2 并须人工 review + 显式摄入命令，**不允许 Agent 自动写**。

**简化原则**：llm_wiki 摄入路径极重（长文档分块断点续传、截断修复、step3 独立评审、LLM body 合并、page-history 备份、overview.md、REVIEW block、9 类页、图谱 4 信号相关度）。本设计按下表裁剪：

| llm_wiki 机制 | 本设计取舍 | 理由 |
| --- | --- | --- |
| 两步 LLM 摄入（分析→生成 FILE block） | **保留，简化** | 复利核心，不可砍 |
| 9 类 wiki 页 | **P0 仅 4 类**（source/entity/concept/process） | 企业知识库 YAGNI |
| 长文档分块 + 断点续传 | **砍** | P0 文档均小；留接口，超长走确定性按 section 截断 |
| 截断 FILE block 修复 | **砍** | 依赖重；改为丢弃未闭合 block + warn |
| step3 独立评审 REVIEW block | **砍** | 人工 review 替代；P0 不做 |
| LLM body 合并（多源页）+ 70% 缩水拒绝 + page-history 备份 | **砍**，改"数组并集 + 追加段落" | 简化、可靠、信息不丢 |
| 单源页 body 替换 | **保留** | 重新摄入修正件必须替换 |
| enrich-wikilinks（LLM 回填 wikilink） | **砍**（注意：llm_wiki 自己也未接入主流程） | 简化；关联用 frontmatter `related`（确定性）+ 向量/图谱后置 |
| index.md 确定性重建 | **保留，简化** | Karpathy 复利关键 |
| log.md 确定性追加 | **保留** | 摄入审计 |
| overview.md | **砍**（llm_wiki 也半放弃） | YAGNI |
| ingest-cache（sha256 + 落盘校验防幽灵） | **保留** | 避免重复 LLM 调用 |
| isSafeIngestPath 路径注入防护 | **保留** | LLM 生成路径必须校验 |
| 手写加权打分（伪 BM25） | **不照搬**，改 `rank-bm25` BM25Okapi | 真 BM25 质量更好（用户认可的唯一不照搬点） |
| CJK bigram 分词 | **保留**（用 jieba + CJK bigram，F7） | 中文召回兜底 |
| LanceDB 向量 + per-page blend | **留 M3** | P0 不装向量环境 |
| RRF（keyword+vector） | **保留接口**，P0 单路直通 | 向量化后注册即两路 |
| 4 信号图谱相关度 | **砍**（留 M3+） | 关联用 `related` 先顶 |

---

## 一、架构与模块布局

M1 产出 `md/{cat}/{doc_id}.md`（带 section 元数据）。M2 在其上构建**复利 wiki 层**：LLM 两步摄入把 md 文件消化成 wiki 页，确定性维护目录与日志，BM25 索引 wiki 页。

```
md/{cat}/{doc_id}.md  ──▶ 两步 LLM 摄入 ──▶ wiki/*.md（复利知识载体）
                          (ingest/wiki)
                              │
                              ├─ source 摘要页   wiki/sources/{slug}.md
                              ├─ entity 页       wiki/entities/{slug}.md
                              ├─ concept 页      wiki/concepts/{slug}.md
                              └─ process 页      wiki/process/{slug}.md
                              │
            写完每页 → frontmatter 数组并集合并(已有页) / 单源页替换
            写完本次 → 确定性重建 index.md / 追加 log.md
                              │
wiki/*.md  ──▶ BM25Retriever(rank-bm25, over wiki 页 section) ──▶ kb search
            (retrieval, jieba+CJK bigram F7)
            RRFFuser 接口摆好, P0 单路直通; 向量路 M3 注册
```

**新增模块（`l1_kb/` 下）**：

```
l1_kb/
├── llm/                          # 新增
│   ├── __init__.py
│   ├── client.py                 # OpenAI 兼容薄封装: 读 env, chat_json() / chat_text()
│   └── ingest_prompts.py         # step1/step2 prompt 构造 (吸收 llm_wiki buildAnalysis/GenerationPrompt 原理)
├── ingest/                       # M1 已有 cleaners/section_splitter/doc_id/safe_path/clean
│   ├── wiki/                     # 新增: 复利 wiki 摄入
│   │   ├── __init__.py
│   │   ├── page_types.py         # 4 类页 + dir↔type 映射 + frontmatter schema
│   │   ├── frontmatter.py        # 解析/序列化 frontmatter (YAML, 数组字段)
│   │   ├── safe_path.py          # is_safe_wiki_path (吸收 llm_wiki isSafeIngestPath 原理)
│   │   ├── file_blocks.py        # 解析 ---FILE:...---...---END FILE--- block
│   │   ├── merge.py              # 已有页合并: frontmatter 数组并集 + body 追加段落 / 单源页替换
│   │   ├── index_log.py          # 确定性重建 index.md / 追加 log.md (吸收 llm_wiki 原理)
│   │   ├── ingest_cache.py       # sha256(content) + 落盘校验防幽灵 (吸收 llm_wiki 原理)
│   │   └── ingest.py             # 编排: md 文件 → 两步 LLM → 写 wiki 页 → 合并 → 重建 index/log
│   └── ... (M1 不动)
├── retrieval/                    # 新增
│   ├── __init__.py
│   ├── base.py                   # Retriever ABC + SearchHit + RRFFuser (M2 spec 原设计保留)
│   ├── tokenizer.py              # jieba + CJK bigram (F7), 保留
│   ├── bm25.py                   # BM25Retriever(rank-bm25): 索引 wiki 页 section
│   └── snippet.py                # 按 line_start/end 从 wiki 页原文切 snippet
├── config.py                     # 新增: 集中读 env (路径 + LLM 配置)
└── cli/kb.py                     # 扩展: + kb ingest / kb search / kb index(重建)  (lint 留 M3)
```

**边界守卫**：以上全部是**离线摄入脚本**（写 `wiki/`）与**只读 CLI 检索**，无任何 Agent 操作工具——CLAUDE.md 硬约束 ② 不受影响。L1 摄入脚本写 `wiki/*.md` 属正常生成物，非 Agent action tool（同 M1 写 `md/` 的定性）。

---

## 二、4 类 wiki 页与 frontmatter schema（`ingest/wiki/page_types.py` + `frontmatter.py`）

### 2.1 页类型（P0 四类）

吸收 llm_wiki `GENERATION_WIKI_TYPES`（9 类）裁剪为 4 类，适配企业知识库场景：

| type | 目录 | 用途 | 何时生成 |
| --- | --- | --- | --- |
| `source` | `wiki/sources/` | 一份原件的摘要页（人/物/时/摘要/关键字段表）| 每次摄入必产 1 张 |
| `entity` | `wiki/entities/` | 实体页（数据表、API、系统、角色等业务对象）| step1 识别出则产 |
| `concept` | `wiki/concepts/` | 概念页（业务术语、口径、定义）| step1 识别出则产 |
| `process` | `wiki/process/` | **流程页**（审批流/制度编号 PRC-xxx/步骤/责任人/上下游/触发条件）| step1 识别出则产（企业场景新增，对应规章流程文档）|

> `process` 是本设计**新增**类型（llm_wiki 无），专门承载企业流程/制度文档的结构化信息（流程编号、步骤、责任人、上下游系统、触发条件），契合 PRD §13.2「流程编号召回」用例。dir↔type 双向校验同 llm_wiki `validateWikiPageRouting`（type 与所在目录不符则丢弃该 FILE block）。

### 2.2 统一 frontmatter schema

吸收 llm_wiki 统一 7 字段（`type/title/created/updated/tags/related/sources`）。所有页（除 `log.md`）首行必须 `---`，YAML 内联数组：

```yaml
---
type: source
title: "订单明细表 order_detail"
created: 2026-07-31
updated: 2026-07-31
tags: [订单, 数据表, order]
related: [entity_order_detail, concept_order_status]
sources: [data_table/order_detail.xlsx]
---
```

- `related` 存**裸 slug**（不带 `wiki/` `.md` `[[]]`）——吸收 llm_wiki 设计，确定性、可校验、与 wikilink 解耦。
- `sources` 必须含当前原件的 `source_identity`（相对 raw 路径）；`canonicalize_sources_field` 强制注入并过滤非法引用（拒绝对路径、`..`、`index/log`、`.llm-wiki/`）。
- `created` 仅新页置今日；`updated` 每次写入置今日（`stamp_dates` 强制）。

### 2.3 slug 与 source_identity

- `source_identity` = 相对 `raw/` 的路径（含子目录），如 `data_table/order_detail.xlsx`。source 摘要页路径 = `wiki/sources/{slug}.md`，slug = 去扩展名的路径段（多段用 `_` 连，与 M1 `slugify_path` 一致）。
- entity/concept/process 的 slug 由 step2 LLM 生成（英文小写 + `_`，如 `entity_order_detail`），代码做 sanitize（仅 `[a-z0-9_]`，空兜底）。

---

## 三、两步 LLM 摄入（`llm/` + `ingest/wiki/ingest.py`）

吸收 llm_wiki `ingest.ts` 两步流（`buildAnalysisPrompt` → `buildGenerationPrompt` → `parseFileBlocks` → `writeFileBlocks`），简化如下。

### 3.1 `config.py`（集中读 env）

- `RAW_ROOT` / `MD_ROOT` / `WIKI_ROOT`（默认 `l1_kb/knowledge_base/wiki/`）
- `LLM_BASE_URL`（默认 `https://api.deepseek.com/v1`）、`LLM_API_KEY`（`DEEPSEEK_API_KEY`）、`LLM_MODEL`（默认 `deepseek-chat`）
- 全部可被 env 覆盖；公司内部 OpenAI 兼容端点日后换 env 即可（CLAUDE.md ③）。

### 3.2 `client.py` — OpenAI 兼容薄封装

- `chat_json(system, user) -> dict`：`response_format={"type":"json_object"}`，解析 JSON，非法重试一次，仍失败抛 `LLMError`。
- `chat_text(system, user, max_tokens) -> str`：纯文本出（step2 FILE block 用）。
- 无流式、无工具——纯结构化进出。单步超时 60s，失败即降级。

### 3.3 Step 1 — 分析（`chat_json`，temperature 0.1）

吸收 llm_wiki step1：注入当前 `wiki/index.md`（判断实体是否已存在）+ purpose + 源文本。输出**结构化 JSON**（llm_wiki 是自由 markdown，本设计简化为 JSON 更易解析）：

```python
def step1_analyze(client, source_identity, md_text, index_md) -> dict:
    """→ {
        "entities": [{"name","slug","role","exists":bool}],
        "concepts": [{"name","slug","definition","exists":bool}],
        "processes": [{"name","slug","code"(PRC-xxx),"owner","steps":[],"upstream","downstream","exists":bool}],
        "summary": "3-5 句摘要",
        "keywords": ["字段名/编号/术语"],
    }"""
```

- `exists` 由 LLM 对照注入的 index 判断；代码交叉校验（与磁盘实际 slug 集合比对，纠正幻觉）。
- purpose/system prompt 明确：编目员角色，JSON-only，`type∈{source,entity,concept,process}`，summary 点到为止，keywords 须含字段名/流程编号。

### 3.4 Step 2 — 生成 FILE block（`chat_text`，temperature 0.1）

吸收 llm_wiki step2：注入 schema + purpose + index + source_identity + step1 分析（标注 "context only, do not repeat"）+ 源文本。输出严格 FILE block 格式：

```
---FILE: wiki/sources/{slug}.md---
<frontmatter + body>
---END FILE---
---FILE: wiki/entities/{slug}.md---
<frontmatter + body>
---END FILE---
```

- prompt 强制：**必产 1 张 source 摘要页**（路径 = `wiki/sources/{slug}.md`），可选若干 entity/concept/process 页。
- 禁止生成 `index.md`/`log.md`/`overview.md`（由应用确定性维护；LLM 若生成则丢弃 + warn，吸收 llm_wiki `isAppManagedAggregatePath`）。
- `max_tokens` 按 context window 分档（8192/16384/24576）。

### 3.5 `file_blocks.py` — 解析 FILE block

吸收 llm_wiki `parseFileBlocks` + `FILE_BLOCK_REGEX`，简化：
- 正则 `---FILE:\s*([^\n]+?)\s*---\n([\s\S]*?)---END FILE---` 提取 `{path, content}`。
- **未闭合 block（截断）→ 丢弃 + warn**（不调 LLM 修复，砍 llm_wiki 截断修复路径）。
- 每个 path 过 `is_safe_wiki_path`（见 §3.7），不通过则丢弃 + warn。

### 3.6 写入与合并（`merge.py` + `ingest.py` 编排）

吸收 llm_wiki `writeFileBlocks` + `mergePageContent`，**简化合并策略**（用户确认）：

```
for each FILE block:
  path, content = parse
  if not is_safe_wiki_path(path): warn; continue
  content = sanitize_frontmatter(content); stamp_dates(content)   # 强制 created/updated
  canonicalize_sources(content, source_identity)                  # 强制 sources 含当前源
  validate_routing(path, content.type)                            # type↔dir 一致
  if 已存在该页:
    existing = read
    if existing.sources == [当前源]:    # 单源页 → 替换 body (吸收 llm_wiki replaceExistingBody)
        merged_body = new_body
    else:                              # 多源页 → 追加段落 (本设计简化, 砍 LLM body 合并)
        merged_body = existing_body + f"\n\n## 来源补充: {source_identity}\n\n" + new_body
    merged_frontmatter = union_arrays(existing.fm, new.fm)         # sources/tags/related 并集 (吸收 llm_wiki UNION_FIELDS)
    locked = existing.locked_fields(type/title/created)            # 吸收 llm_wiki LOCKED_FIELDS
    write(merged)
  else:
    write(content)
```

- 数组字段并集是确定性、零 LLM、零成本，跨源保留所有贡献（吸收 llm_wiki `UNION_FIELDS`）。
- locked 字段（type/title/created）强制回填旧值（吸收 llm_wiki `LOCKED_FIELDS`）。
- **砍掉** LLM body 合并、70% 缩水拒绝、page-history 备份；多源页用"追加段落"保证信息不丢（body 略冗长但可靠）。

### 3.7 `safe_path.py` — `is_safe_wiki_path`（吸收 llm_wiki `isSafeIngestPath` 原理）

LLM 生成的 path 来自不可信文本（源文档可能含 prompt injection）。校验：
- 非空、无控制字符/`\x00-\x1f`、非绝对路径（`/` `\`）、非 Windows 盘符。
- 反斜杠归一 `/`；任一段含 `..` → 拒绝。
- 必须 `wiki/` 前缀。
- 中文等非 ASCII 允许在 leaf 段（slug 已 sanitize 成 `[a-z0-9_]`，故实际安全）。

### 3.8 `ingest_cache.py`（吸收 llm_wiki `ingest-cache.ts` 原理）

- `check_cache(source_identity, content_hash)`：命中**仅当** sha256 匹配 **且** 之前写入的所有 wiki 页仍存在于磁盘（防幽灵条目——某页被人删了则视为未摄入，重跑）。
- 命中跳过两步 LLM（省调用）；未命中跑完写入后 `save_cache(identity, hash, written_paths)`。
- 缓存文件 `l1_kb/knowledge_base/.cache/ingest-cache.json`。

### 3.9 优雅降级

`LLM_API_KEY` 未设或调用失败（重试后）→ `step1_analyze`/`step2_generate` 走确定性回退（吸收 llm_wiki `buildFallbackSourceSummary`）：
- 产**仅 1 张 source 摘要页**：title ← `Source: {identity}`，body ← M1 sections 拼接的标题 + 首段（或 `"(Analysis not available)"`），keywords ← tokenizer 高频 token top-N，tags/related 空，`sources=[identity]`。
- `meta` 不写 LLM 字段；BM25 索引只依赖 wiki 页文本，不依赖 LLM 归纳字段——故无网络也能产出可检索 wiki，§13.2 验收不依赖 LLM。

---

## 四、确定性 index.md / log.md（`ingest/wiki/index_log.py`）

吸收 llm_wiki `updateWikiIndexDeterministically` + `buildDeterministicIngestLog`（**不用 LLM**）。

### 4.1 `index.md` — 重建

```
遍历 wiki/*.md（排除 index/log/overview 茎）
  → 按 frontmatter type 分组（source/entity/concept/process）
  → 每组按 title 排序
  → 写:
     # Wiki Index
     ## source
     - [[{slug}|{title}]]
     ## entity
     - [[{slug}|{title}]]
     ...
  → 原子写：tmp + rename
```
（吸收 llm_wiki `rebuild_wiki_index_inner`：BTreeMap 排序、按 type 分组、`[[{slug}|{title}]]` 行、原子 temp+rename。）

`kb index` 命令触发全量重建（吸收 llm_wiki `rebuild_wiki_index`）；`kb ingest` 每次跑完也增量重建一次。

### 4.2 `log.md` — 追加

```
## [YYYY-MM-DD] ingest | {source_identity}
```
每次摄入追加一行（吸收 llm_wiki `buildDeterministicIngestLog`）。首行 `# Wiki Log`。文件不存在则建。

---

## 五、BM25 检索（`retrieval/`）

> 砍掉 index.json；BM25 **直接索引 wiki 页**。wiki 页即知识载体，检索单元 = wiki 页 section。

### 5.1 接口层 `base.py`（保留 M2 spec 原设计）

```python
@dataclass
class SearchHit:
    doc_id: str            # wiki 页 slug（如 entity_order_detail）
    section_id: str        # s0, s1, ...
    title: str             # wiki 页 title（frontmatter）+ section 标题
    snippet: str
    score: float           # RRF 融合后
    source: str            # 'bm25' | 'vector'

class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, top_n: int = 50) -> list[SearchHit]: ...

class RRFFuser:
    def fuse(self, results: list[list[SearchHit]], k: int = 60, top_k: int = 10) -> list[SearchHit]: ...
```
- P0 仅注册 `BM25Retriever`，`fuse([bm25])` 单路直通（去重 + 截断）。向量化后 `register(VectorRetriever)` 即两路，契约不变（吸收 llm_wiki RRF k=60）。

### 5.2 分词 `tokenizer.py`（jieba + CJK bigram，F7，保留）

```python
def tokenize(text: str) -> list[str]:
    tokens = set(jieba.cut_for_search(text))
    for run in _CJK_RE.findall(text):
        for i in range(len(run) - 1):
            tokens.add(run[i:i + 2])
    return [t for t in tokens if t.strip()]
```

### 5.3 BM25 检索器 `bm25.py`

文档单元文本 = wiki 页 section 的「frontmatter title + section 标题 + 正文」。`rank-bm25` `BM25Okapi`（IDF + 文档长度归一，**真 BM25**，不照搬 llm_wiki 手写打分）。纯内存，每次运行重建。

```python
class BM25Retriever(Retriever):
    def __init__(self, entries: list[dict]) -> None:
        """entries: [{slug, section_id, title, body_text}] from wiki/*.md sections."""
        self._meta = entries
        self._corpus = [tokenize(f"{e['title']} {e['body_text']}") for e in entries]
        self._bm25 = BM25Okapi(self._corpus)
    def search(self, query, top_n=50) -> list[SearchHit]: ...
```

### 5.4 wiki 页 → section entries

`kb search` 启动时扫描 `wiki/*.md`，复用 M1 `SectionSplitter.split` 切 section（wiki 页也是 ATX 标题 + pipe 表 markdown，M1 splitter 适用），每个 section 成一个 entry。frontmatter title 作为页级 title 前缀注入。

### 5.5 `snippet.py`（保留）

按 section 行号从 wiki 页原文切 snippet，max_chars=500。

### 5.6 查询流程 `kb search "order_id"`

```
kb search "order_id"
  → 扫 wiki/*.md → SectionSplitter → entries
  → BM25Retriever.search("order_id", top_n=50)
  → RRFFuser.fuse([bm25_hits], k=60, top_k=10)
  → 每条 hit: make_snippet(wiki[slug], line_start, line_end)
  → 按 §11.2 打印
```

### 5.7 验收对齐（§13.2）

| 用例 | 命令 | 期望 |
| --- | --- | --- |
| 精确词召回 | `kb search "order_id"` | top_5 命中含 `order_id` 的 wiki 页 section（entity_order_detail / source 摘要页字段表），snippet 含该字段行 |
| 流程编号召回 | `kb search "PRC-2024-003"` | top_5 命中含该编号的 process 页 / source 摘要页 section |
| 语义召回 | — | P0 不要求，向量就绪后验（§13.2 第 3 行） |

**LLM-fallback 路径同样须通过**这两类：fallback 仍产 source 摘要页含字段表，BM25 只依赖 wiki 页文本。

---

## 六、错误处理 + 测试 + 验收

### 6.1 错误处理矩阵

| 场景 | 处理 | 结果 |
| --- | --- | --- |
| `LLM_API_KEY` 未设/调用失败 | 走确定性 fallback（§3.9），产仅 source 摘要页 | 摄入继续，wiki 可检索 |
| LLM 返回非法 JSON | 重试一次；仍失败降级 fallback | 同上 |
| FILE block 未闭合（截断） | 丢弃该 block + warn，保留其余 | 部分成功 |
| LLM 生成非法 path（`..`/绝对路径） | `is_safe_wiki_path` 拒绝 + warn | 跳过该页 |
| type↔dir 不一致 | 丢弃该 block + warn | 跳过 |
| 源 md 缺失 | 跳过 + warn | 部分成功 |
| BM25 空查询/空语料 | 返回 `[]` | 不崩 |
| ingest-cache 命中但页被删 | 视为未摄入，重跑两步 | 防幽灵 |

> 摄入侧容错降级；查询侧纯本地不依赖 LLM。

### 6.2 测试策略（`tests/`，pytest，CI 不要求 `DEEPSEEK_API_KEY`）

**单元**：
- `page_types`：dir↔type 双向校验；非法 type 拒绝。
- `frontmatter`：解析/序列化往返；数组字段并集。
- `safe_path`：`..`/绝对路径/控制字符/非 `wiki/` 前缀 → False。
- `file_blocks`：正常解析；截断 block 丢弃；多 block。
- `merge`：新页写入；单源页替换；多源页追加段落；数组并集；locked 字段不被覆盖。
- `index_log`：index.md 按 type 分组排序正确；log.md 追加不重复。
- `ingest_cache`：sha256 命中跳过；页被删则失效重跑。
- `tokenizer` F7：`order_id`→`["order_id"]`；`订单状态`含`订单/单状/状态`bigram。
- `BM25Retriever`：固定小语料排序；top_5 截断；空输入 `[]`。
- `RRFFuser`：单路直通；去重；`1/(k+rank)` 正确。
- `snippet`：命中词行被含入。
- **`ingest` 两步**：**必须 mock LLM client**（注入返回固定 JSON/text 的假 client），断言产 source + entity/concept/process 页、frontmatter 正确、index/log 更新；再断言 `client=None` 时 fallback 产仅 source 摘要页。

**集成**：`kb ingest` 端到端（5 份 M1 样本）写合法 wiki 页 + index.md + log.md；`kb search "order_id"`/`"PRC-2024-003"` 端到端返回 section 级结果。

### 6.3 通过判据

§13.2 精确词 + 流程编号两类用例 top_5 命中正确 section 为 M2 必过项；fallback 路径同样须通过。

### 6.4 验证命令

```bash
pytest tests/ -q
kb ingest                     # 对 5 份 md 样本摄入 wiki
kb index                      # 重建 index.md（确定性）
kb search "order_id" && kb search "PRC-2024-003"
```

---

## 七、依赖（pyproject.toml 增量）

**运行时新增**：
- `openai`（OpenAI 兼容客户端）
- `jieba`（中文分词）
- `rank-bm25`（BM25Okapi）
- `pyyaml`（frontmatter 解析/序列化）

**不进 M2**：`bge-m3`/`sentence-transformers`/`numpy`（向量，M3）/`lancedb`（向量库，M3）/`fastapi`/`uvicorn`（REST API，M4）/`watchdog`（watch，M3）。

清华镜像：`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。

---

## 八、实现顺序

1. `pyproject.toml` 加依赖 + `uv pip install`（openai/jieba/rank-bm25/pyyaml）。
2. `config.py`。
3. `ingest/wiki/{page_types,frontmatter,safe_path}.py` + 单测（最纯，先立基）。
4. `ingest/wiki/{file_blocks,merge,index_log,ingest_cache}.py` + 单测。
5. `llm/{client,ingest_prompts}.py` + `ingest/wiki/ingest.py` 编排 + 单测（mock client，含 fallback）。
6. `retrieval/{base,tokenizer,bm25,snippet}.py` + 单测（F7/排序/RRF/snippet）。
7. `cli/kb.py` 扩展 `kb ingest`/`kb index`/`kb search`。
8. 端到端：`kb ingest` → `kb index` → `kb search` 跑 §13.2 + pytest 全绿。
9. commit。

---

## 九、待决议（实现中如遇则定，否则按倾向）

- **keywords 回退 top-N**：倾向 top-5 高频 token（去停用词）。
- **snippet max_chars**：500。
- **LLM 超时**：单步 60s，失败即降级。
- **多源页追加段落的去重**：若新 body 与已有某段落高度重复，倾向保留已有（简单：若 new_body 完全被 existing_body 包含则不追加）。
- **process 页 code 字段抽取**：倾向 step1 LLM 直接给 `PRC-xxx`，代码只 sanitize。

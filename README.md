# kb-retrieval-sys

企业内部知识库检索系统 —— 把 ~1000 份 PDF / Word / Excel / Markdown 文档清洗成结构化 markdown，归纳成可检索的知识 wiki，对外提供只读检索 API（供后续 L2 Agent 调用）。

> 设计文档：[docs/architecture_3layer.md](docs/architecture_3layer.md)（三层架构）、[docs/kb_retrieval_solutions.md](docs/kb_retrieval_solutions.md)（检索方案调研）、[docs/superpowers/specs/](docs/superpowers/specs/)（里程碑设计稿）。

---

## 架构（三层）

| 层 | 职责 | 技术 | 状态 |
| --- | --- | --- | --- |
| **L1 知识库层** | PDF→MD 清洗 + wiki 归纳 + 增量摄入 + BM25 检索 + 自检/重建 + 只读 REST API | Python / Click / OpenAI 兼容 LLM / FastAPI | ✅ 已完成（M1–M4） |
| **L2 Agent 层** | 多跳检索编排、自评重试、带引用总结；OpenAI 兼容端点 | TypeScript / pi | ⏳ 待开始（M5） |
| **L3 交互层** | 对话提问、展示带来源引用的答案 | Open WebUI | ⏳ 待开始（M6） |

**层间契约**（稳定）：
- L3 → L2：OpenAI 兼容 `/v1/chat/completions`
- L2 → L1：只读 REST API（`/categories` `/documents` `/search` `/documents/{id}` `/index` `/health`），**无写入/执行端点**
- L2 → LLM：OpenAI 兼容端点（可配置 base URL / key / model）

本仓库当前只交付 **L1 层**。L1 既是离线摄入 pipeline（写 md/wiki/index），也是在线只读检索来源；L2/L3 尚未开始。

---

## 硬约束

1. **独立项目**：本目录自包含，不依赖仓库其他文件夹。
2. **仅文档查询，不执行动作**：Agent 工具边界严格只读。L1 摄入脚本是**离线脚本**（写 md/wiki 属正常），不是 Agent 工具。
3. **全部自托管**：LLM 走公司内部 OpenAI 兼容服务，不依赖外部 SaaS。
4. **基于 Agent，非工作流**：检索由 Agent 自主规划（多跳 + 自评重试）。
5. **GPL 红线**：仅借鉴方法论，用 Python 重实现，绝不 import / copy GPL 源码。

---

## 目录结构

```
kb-retrieval-sys/
├── l1_kb/
│   ├── ingest/
│   │   ├── cleaners/          # PDF/Word/Excel/MD 四类清洗器 + dispatcher
│   │   ├── section_splitter.py# 按标题切 section（检索/索引/加载单元）
│   │   ├── doc_id.py          # slug + sha256[:8]，不含 category（稳定身份）
│   │   ├── safe_path.py       # 路径越界校验
│   │   ├── clean.py           # 编排：raw → md/ + sections
│   │   ├── wiki/              # M2：md → LLM 两步归纳 → wiki/{sources,entities,concepts,process}
│   │   └── incremental/       # M3：hash.json 变更检测 + 三态增量 + ingest_log
│   ├── retrieval/             # BM25 + RRF + snippet
│   ├── lint/                  # 五项确定性自检（L1_FORMAT…L5_GAP）
│   ├── cli/kb.py              # CLI 入口
│   ├── service/               # M4 只读 REST API（FastAPI，6 GET 端点）
│   └── knowledge_base/
│       ├── raw/               # 原件（入库，分类子目录）
│       ├── md/                # 清洗产物（.gitignore）
│       ├── wiki/              # 知识 wiki（.gitignore）
│       └── .cache/            # hash.json + ingest-cache.json（.gitignore）
├── tests/                     # 单测（mock LLM）+ e2e（真 key）
└── pyproject.toml             # uv 管理
```

---

## 安装

需要 Python ≥ 3.12，推荐用 [uv](https://docs.astral.sh/uv/)：

```bash
# 1. 建虚拟环境
uv venv .venv
source .venv/bin/activate

# 2. 装运行时依赖（含 dev）
uv pip install -e ".[dev]"

# 3.（可选）Word 清洗依赖 pandoc；未装则 .docx 优雅跳过
which pandoc || echo "pandoc 未装，.docx 将跳过"
```

验证安装：

```bash
.venv/bin/python -m l1_kb.cli.kb --help
# 或装入口后：kb --help
```

---

## LLM 配置（可选但推荐）

L1 的 **wiki 归纳**（M2）调 LLM 把 md → 知识页。无 key 时自动走**确定性 fallback**（只写 source 页，跳过 entity/concept/process 归纳），检索仍可用但召回较粗。

默认接 DeepSeek（公司内部可换任意 OpenAI 兼容端点）。全部走 env，**不写进任何文件**：

| env | 默认 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容 base URL |
| `LLM_API_KEY` 或 `DEEPSEEK_API_KEY` | （空） | API key；有则启用 LLM，无则 fallback |
| `LLM_MODEL` 或 `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `KB_TODAY` | （系统今日） | 日期戳，测试/可重复跑用 |

示例：

```bash
export LLM_API_KEY=sk-xxxxx
export LLM_MODEL=deepseek-v4-flash
```

---

## 数据流（一图理解）

```
raw/原件              md/结构化             wiki/知识页            检索
─────────            ──────────           ────────────          ──────
order_detail.xlsx ──clean──► order_detail__*.md ──ingest(LLM)──► sources/*.md ──search(BM25)──► 命中片段
                                                              ├── entities/*.md
                                              index.md ←──────┤── concepts/*.md
                                              log.md          └── process/*.md
```

- `clean`：raw → md（确定性，不调 LLM）。
- `ingest`：md → wiki（调 LLM 两步归纳；首次写入，重复跑用 hash.json + ingest-cache 跳过）。
- `search`：在 wiki 上做 BM25 检索。
- 增量：改/删 raw 后再 `ingest`，自动三态（add/modify/delete）同步 wiki。

---

## 三步核心流程详解（代码内流程）

下面三张流程图按代码实际调用链展开（文件名/函数名标注在节点上），说明每一步在做什么、读写哪些产物。

### 1️⃣ `kb clean`：raw → md（确定性，不调 LLM）

入口 `cli/kb.py:clean` → `ingest/clean.py:clean_one`。逐文件递归，每文件独立清洗。

```
┌─────────────────────────────────────────────────────────────────────────┐
│ kb clean <PATH>                                                          │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  递归遍历 PATH 下 SUPPORTED_EXTS (.pdf/.docx/.xlsx/.md) 文件
        │  对每个文件 f 执行 clean_one(raw_root, f, md_root) ──┐
        │                                                      │
        │   ┌──────────────────────────────────────────────────┘
        │   │
        │   ▼ ① safe_path.is_safe_path(raw_root, f)
        │      resolve 后是否在 raw_root 内、是文件、非跳出软链？
        │      └─ 否 → 返回 skipped(reason="路径不安全")，CLI warn 跳过
        │   │
        │   ▼ ② doc_id.make_doc_id(raw_root, f)
        │      rel = f 相对 raw_root (data_table/order_detail.xlsx)
        │      slug = slugify_path(rel) → "data_table_order_detail"
        │            (去扩展名, 非[a-zA-Z0-9]→_, 连续_压缩, 小写)
        │      digest = sha256(f.read_bytes())[:8]
        │      doc_id = f"{slug}__{digest}"   ← 不含 category(稳定身份)
        │   │
        │   ▼ ③ _derive_category(raw_root, f) → "data_table"
        │      (临时: raw 相对路径第一段; M2 LLM 会重分类, 不影响 doc_id)
        │   │
        │   ▼ ④ cleaners.dispatcher.cleaner_for(f) → 选 Cleaner
        │      .pdf  → PdfCleaner   (pymupdf4llm 权威 + pdfplumber 表格兜底)
        │      .docx → WordCleaner  (pandoc; 未装则 raise PandocNotAvailableError→skipped)
        │      .xlsx → ExcelCleaner (openpyxl+pandas; 宽表>20列触发字段分组 F4)
        │      .md   → MarkdownCleaner (ATX 规范化)
        │      md_text = cleaner.to_markdown(f)   ← 带 #/##/### + pipe 表
        │   │
        │   ▼ ⑤ section_splitter.split(md_text) → list[Section]
        │      扫 ^#{1,3}\s 标题行 → 相邻标题间为一个 section
        │      Section(section_id=s0/s1.., title, line_start, line_end, level,
        │              is_table=正文首行以|开头→豁免200行二次切分)
        │      过长(>200行)且非表 → 按空行二次切分
        │   │
        │   ▼ ⑥ 写盘 (非 dry-run)
        │      md_path = md_root/{category}/{doc_id}.md
        │      md_path.write_text(md_text)
        │   │
        │   └─► CleanResult(doc_id, category, md_path, sections)
        │
        ▼
  CLI 汇总: 完成: 成功 N, 跳过 M, 失败 K (共 X 文件)
  产物: md/{category}/{doc_id}.md   (doc_id 即后续一切的身份锚点)
```

**关键设计**：`doc_id` 由「raw 相对路径 + sha256(字节)」派生，**不含 category**。这让 LLM 重分类、文件迁移都不破坏身份与引用——后续 ingest/检索/增量都靠它对齐。

### 2️⃣ `kb ingest`：md → wiki（LLM 两步归纳 + 增量三态）

入口 `cli/kb.py:ingest`。PATH 在 `raw_root` 下 → 走 M3 增量（`incremental/ingest_flow.py`）；在 `md_root` 下 → 走 M2 直摄入（向后兼容）。下图为 raw 三态主流程。

```
┌─────────────────────────────────────────────────────────────────────────┐
│ kb ingest <raw_root>                                                     │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼  client = make_client_from_config()   (无 key → None→fallback)
        │
        ▼  ingest_flow.run_incremental(...)
        │
        ▼  change_detect.detect_changes(raw_root, hash.json)
        │   扫 raw/ 每个支持文件 → 算 sha256 → 对比 hash.json 记录 → 四态:
        │
        │   ┌──────────┬─────────────────────────────────────────────┐
        │   │ add      │ hash.json 无记录 + raw 存在                   │
        │   │ modify   │ 有记录但 sha256 变了                          │
        │   │ skip     │ 有记录且 sha256 不变  ← 整文件跳过            │
        │   │ delete   │ hash.json 有记录但 raw 文件已删               │
        │   └──────────┴─────────────────────────────────────────────┘
        │
        ├───────────────────── add / modify ──────────────────────────────┐
        │                                                                 │
        │   modify 先 purge_source(purge_md=False)  ← delete-then-add     │
        │   (删旧 wiki 页 + 旧 cache 条目, 但保留新 md 供下面摄入)          │
        │                                                                 │
        │   ▼ _ingest_one(item, action=add|modify)
        │      ┌────────────────────────────────────────────────────────┐
        │      │ (a) delete.find_md_for_slug(md_root, slug)             │
        │      │     glob **/{slug}__*.md → md 绝对路径 (无则 warn 跳过) │
        │      │                                                        │
        │      │ (b) wiki.ingest.ingest_source(md_path, identity=md路径,│
        │      │         wiki_root, cache_path, client, today)          │
        │      │   ┌──────────────────────────────────────────────────┐ │
        │      │   │ 1. content_hash(md_text) = sha256(正文)           │ │
        │      │   │ 2. check_cache(identity, hash)?                   │ │
        │      │   │    命中(hash 同 且 written_paths 全在盘上)→ skip   │ │
        │      │   │ 3. client 有? → _two_step_llm:                     │ │
        │      │   │      step1: chat_json(分析→JSON: 类型/标题/related)│ │
        │      │   │      step2: chat_text(生成 FILE block 列表)        │ │
        │      │   │      parse_file_blocks → [(path, content), ...]    │ │
        │      │   │    LLM 失败/无 client → build_fallback_pages       │ │
        │      │   │      (确定性: 仅 1 张 source 摘要页, 标题+首段)     │ │
        │      │   │ 4. 对每个 page:                                    │ │
        │      │   │      normalize_wiki_path (processes→process 别名)  │ │
        │      │   │      merge_page(existing_text, content) → 合并     │ │
        │      │   │      wiki_root/{sources|entities|...}/{slug}.md    │ │
        │      │   │ 5. rebuild_index(wiki_root) → index.md (确定性)    │ │
        │      │   │ 6. append_log → wiki/log.md                       │ │
        │      │   │ 7. save_cache(identity, hash, written_paths)       │ │
        │      │   └──────────────────────────────────────────────────┘ │
        │      │                                                        │
        │      │ (c) 事务提交: hash_store.upsert_hash(                  │
        │      │       slug, hash=raw sha256, path, ingested_at)         │
        │      │     ← hash.json 最后落盘 = 提交标记                     │
        │      │ (d) ingest_log.append_ingest(action=add|modify)         │
        │      └────────────────────────────────────────────────────────┘
        │                                                                 │
        ├───────────────────── skip ─────────────────────────────────────┘
        │   整文件不处理 (summ.skipped += 1)
        │
        ├───────────────────── delete ──────────────────────────────────┐
        │   ▼ purge_source(slug, purge_md=True)                          │
        │     页面定位 3 策略:                                            │
        │       1. 遍历 cache 所有 key(=md路径) 反推 slug, 匹配者收集     │
        │          paths[] + 标记该 key 待删 (命中"旧md已删cache还在")    │
        │       2. 当前 md 的 cache 条目补 paths[] (常规 delete)          │
        │       3. 仍空 → glob sources/{slug}__*.md 兜底                 │
        │     删 wiki 页 → 删 cache 条目 → 删 md → remove_hash(slug)     │
        │                → rebuild_index (清幽灵链接)                    │
        │   ▼ ingest_log.append_delete
        │
        ▼
  CLI 汇总: 完成: 新增 X, 修改 Y, 删除 Z, 跳过 W, 失败 V (共 N 文件)
  产物: wiki/{sources,entities,concepts,process}/*.md + index.md + log.md
        .cache/ingest-cache.json (wiki层跳过缓存)
        .cache/hash.json         (raw层变更检测权威)
        ingest_log.jsonl         (时序审计)
```

**两层缓存（方案 A，并存）**：
- `hash.json` = **raw 层权威**：key=slug，value=raw 字节 sha256 + raw 相对路径。决定 add/modify/delete/skip 四态。
- `ingest-cache.json` = **wiki 层跳过缓存**：key=md 绝对路径(`source_identity`)，value=md 正文 sha256 + written_paths。命中则跳过昂贵的两步 LLM。

**事务语义**：`upsert_hash` 是单文档事务的最后一步（commit 标记）。中途崩溃 → hash.json 未更新 → 下次 `detect_changes` 重判为 modify → purge 重摄入 → 自愈。

**modify = delete-then-add**：先 `purge_source(purge_md=False)` 删旧 wiki 页（保留刚 clean 出的新 md），再 `_ingest_one` 重新归纳。保证旧身份的页被清干净，新身份写入。

### 3️⃣ `kb search`：BM25 检索 wiki

入口 `cli/kb.py:search` → `service/search.py`（M4 起 CLI 与 REST 共用同一检索层，DRY）。纯内存，每次运行即时扫 wiki 重建索引（P0 阶段语料小，够用）。

```
┌─────────────────────────────────────────────────────────────────────────┐
│ kb search "<query>" [--top-k N]                                          │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼ ① store.load_store(config.WIKI_ROOT)
        │   扫 wiki/**/*.md (跳过 index/log/overview)
        │   每页: 解析 frontmatter(type/title/updated) + split_sections 切 section
        │   body 经 _truncate(text, max_chars=2000) → 超 2000 字截断 + …[截断] 标记
        │   → WikiStore(pages, by_slug, by_type)
        │
        ▼ ② search.search(store, query, top_k=N)
        │   每个 section → entry {slug, section_id, title, body_text, ...}
        │   BM25Retriever(entries): tokenize(title+body_text) ← jieba 分词
        │   bm25 = BM25Okapi(corpus)                          ← rank-bm25
        │   hits = bm25.search(query, top_n=50)               ← 过滤词频命中防误召回
        │   fused = RRFFuser().fuse([hits], k=60, top_k=N)    ← 单路 RRF 直通 (P0)
        │   snippet = make_snippet(整页原文, line_start, line_end, max_chars=500)
        │   → list[SearchHit(doc_id=slug, section_id, title, snippet, score, source)]
        │
        ▼ ③ 逐 hit 渲染
        │   打印:
        │     [0.8421]  data_table_order_detail__a3f9c1e2 / s1 — 订单表
        │         {snippet 行，4 空格缩进}
        │
        ▼
  无命中 → "无结果"
  产物: 仅终端输出 (search 是只读, 不写任何文件)
```

**关键设计**：
- **检索单元 = section**：与 ingest 的 section 切分复用同一 `section_splitter`，保证「检索/索引/加载」三层一致（PRD §6.3）。
- **纯内存重建**：不持久化倒排索引，P0 语料小（~1000 doc）秒级重建。M4 的 REST `/search` 走同一 `service.search` 路径。
- **CLI 与 REST 共用检索层（M4 DRY）**：`kb search` 与 `/search` 端点都调用 `service.store.load_store` + `service.search.search`，无重复逻辑。
- **对 L2 透明**：检索机制现为 BM25，未来可换混合检索（+向量），但 `/search` 端点契约不变。

---

## CLI 操作步骤

入口：`.venv/bin/python -m l1_kb.cli.kb <命令>`（装入口后可直接 `kb <命令>`）。

### 默认路径

不带 `--*` 选项时，所有命令默认作用于 `l1_kb/knowledge_base/` 下：

| 选项 | 默认 |
| --- | --- |
| `--raw-root` | `l1_kb/knowledge_base/raw` |
| `--md-root` | `l1_kb/knowledge_base/md` |
| `--wiki-root` | `l1_kb/knowledge_base/wiki` |
| `--cache-path` | `l1_kb/knowledge_base/.cache/ingest-cache.json` |
| `--hash-path` | `l1_kb/knowledge_base/.cache/hash.json` |
| `--log-path` | `l1_kb/knowledge_base/ingest_log.jsonl` |

下文示例用默认路径；换目录就传对应 `--*`。

仓库自带 5 份合成样本，可直接照着跑：

```
raw/data_table/order_detail.xlsx   # Excel 2-sheet
raw/data_table/wide_table.xlsx     # Excel 宽表（>20 列，触发分组）
raw/data_product/api_doc.md        # Markdown API 文档
raw/data_product/product_intro.pdf # PDF
raw/process/policy.md              # Markdown 流程制度
```

### 1. 清洗：`kb clean`（raw → md）

把原件转成带 ATX 标题 + pipe 表格的 markdown，按 `{category}/{doc_id}.md` 落盘。

```bash
# 单文件
.venv/bin/python -m l1_kb.cli.kb clean l1_kb/knowledge_base/raw/data_table/order_detail.xlsx

# 整个 raw 目录递归
.venv/bin/python -m l1_kb.cli.kb clean l1_kb/knowledge_base/raw

# 只看概要，不写 md/
.venv/bin/python -m l1_kb.cli.kb clean l1_kb/knowledge_base/raw --dry-run
```

输出示例：
```
[OK] order_detail.xlsx → doc_id=data_table_order_detail__a3f9c1e2 category=data_table sections=2
完成: 成功 5, 跳过 0, 失败 0 (共 5 文件)
```

> **doc_id 稳定性**：`doc_id = slug(raw相对路径) + '__' + sha256(raw字节)[:8]`，**不含 category**。LLM 重分类后迁移 md 路径不影响 doc_id 与引用。

### 2. 摄入：`kb ingest`（md → wiki）

把 md 归纳成知识 wiki 页（source/entity/concept/process），并写入 `index.md` / `log.md`。

```bash
# 摄入整个 raw 目录（走 M3 增量三态：add/modify/delete/skip）
.venv/bin/python -m l1_kb.cli.kb ingest l1_kb/knowledge_base/raw

# 禁用 LLM，强制确定性 fallback（只写 source 页）
.venv/bin/python -m l1_kb.cli.kb ingest l1_kb/knowledge_base/raw --no-llm
```

输出示例：
```
[ADD] data_table_order_detail
完成: 新增 1, 修改 0, 删除 0, 跳过 0, 失败 0 (共 1 文件)
```

**增量三态**（M3）：
- **add**：raw 新文件 → 清洗 + 归纳 + 写 wiki + 记 hash.json。
- **modify**：raw 字节变了（sha256 变）→ 删旧 wiki 页 + 重新归纳（delete-then-add）。
- **delete**：raw 文件没了 → 精确反向清理 wiki 页 + cache + hash.json。
- **skip**：hash 不变 → 整文件跳过（含 cache 命中）。

事务语义：`hash.json` 最后落盘 = 提交标记。中途崩了 → 下次重检测为 modify → 自动重摄入（自愈）。

所有摄入动作记进 `ingest_log.jsonl`（时序审计，type=ingest/delete/lint/rebuild）。

### 3. 检索：`kb search`（BM25）

在 wiki 上做 BM25 检索（jieba 分词 + RRF 单路融合 + snippet 摘要）。

```bash
# 关键词检索
.venv/bin/python -m l1_kb.cli.kb search "订单 字段"

# 限制返回条数
.venv/bin/python -m l1_kb.cli.kb search "order_id" --top-k 5
```

输出示例：
```
[0.8421] data_table_order_detail__a3f9c1e2 / s1 — 订单表
    | order_id | customer |
    | O1       | 张三     |
```

> 当前检索机制对 L2 透明：`/search` 现为 BM25，未来可换混合检索，但端点契约不变。CLI 与 REST 共用同一 `service.search` 检索层（M4 DRY）。

### 4. 重建索引页：`kb index`（确定性）

重建 `wiki/index.md`（wiki 页目录）。纯确定性，不调 LLM。通常 `ingest` 已自动维护，手动跑用于修复。

```bash
.venv/bin/python -m l1_kb.cli.kb index
```

### 5. 自检：`kb lint`（五项确定性检查）

对 wiki 做一致性自检，输出 `lint_report.json` + 终端摘要；**有 error 则退码 1**。

```bash
.venv/bin/python -m l1_kb.cli.kb lint
# 报告默认写 ./lint_report.json，可指定：
.venv/bin/python -m l1_kb.cli.kb lint --out /tmp/lint.json
```

五项：

| 项 | 级别 | 检查内容 |
| --- | --- | --- |
| L1_FORMAT | error | index.md / log.md 头部格式、ingest_log 每行合法 JSON、hash.json/cache.json 可解析 |
| L2_GHOST | error | index.md 链到的页实际不存在 |
| L2_MISSING | warn | wiki 页未被 index.md 收录 |
| L3_ORPHAN | warn | 无入链的孤立页（source 页豁免） |
| L4_XREF | warn | related 交叉引用断链（Jaccard ≥ 0.5 才认） |
| L5_GAP | info | 某类页（entity/concept/process）数量为 0，提示归纳覆盖缺口 |

### 6. 全量重建：`kb rebuild`（兜底）

清空所有生成物（md/wiki/cache/hash/log，**raw 不动**），从 raw 全量重跑。幂等。**默认 dry-run，需 `--yes` 才执行**。

```bash
# 先看会清什么
.venv/bin/python -m l1_kb.cli.kb rebuild

# 确认执行
.venv/bin/python -m l1_kb.cli.kb rebuild --yes
```

---

## 典型工作流

### 首次入库（5 份样本）

```bash
# 0. 配 LLM key（可选，无则 fallback）
export LLM_API_KEY=sk-xxxxx
export LLM_MODEL=deepseek-v4-flash

# 1. 清洗
.venv/bin/python -m l1_kb.cli.kb clean l1_kb/knowledge_base/raw

# 2. 摄入
.venv/bin/python -m l1_kb.cli.kb ingest l1_kb/knowledge_base/raw

# 3. 自检
.venv/bin/python -m l1_kb.cli.kb lint

# 4. 检索验证
.venv/bin/python -m l1_kb.cli.kb search "订单"
```

### 日常增量

改/加/删 raw 文件后，**只需再跑一次 ingest**（自动三态）：

```bash
.venv/bin/python -m l1_kb.cli.kb ingest l1_kb/knowledge_base/raw
```

> M3 砍了 `watch` 常驻监听（手动 loop 即可）。要全自动重跑用 `kb rebuild --yes`。

---

## 测试

```bash
# 全量单测（mock LLM，无需 key）
.venv/bin/python -m pytest tests/ -q

# 只跑 M3 增量相关
.venv/bin/python -m pytest tests/test_hash_store.py tests/test_change_detect.py \
  tests/test_delete.py tests/test_ingest_flow.py tests/test_ingest_log.py \
  tests/test_lint.py tests/test_rebuild.py tests/test_kb_cli_m3.py -q

# e2e 全链（需真 key，无 key 自动 skip）
DEEPSEEK_API_KEY=sk-xxxxx .venv/bin/python -m pytest tests/test_m3_incremental_e2e.py -v
```

策略：单测一律 mock LLM（`monkeypatch.delenv` 掉 key）；e2e 用真 key 跑通 add→modify→delete→lint→search 全链。**真 key 绝不写进任何文件**。

---

## L1 只读 REST API（M4）

把 L1 的检索能力封装成只读 REST 服务（FastAPI），供 L2 pi Agent 调用。**全 GET，只读，无写入/执行端点**（硬约束 2）。

启动：

```bash
.venv/bin/python -m uvicorn l1_kb.service.app:app --port 8011
# 或装入口后
kb-serve
```

端点（全 GET，只读，无写/执行）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 + wiki 页数 + wiki_root + last_updated |
| GET | `/categories` | 类型统计（source/entity/concept/process 各几页，含 count=0） |
| GET | `/documents?type=&page=&page_size=` | 文档摘要分页（返回 {items,page,page_size,total}；items 含 slug/type/title/section_count/updated，不含正文；非法 type → 422） |
| GET | `/documents/{slug}` | 单文档详情（含 slug/type/title/updated/sections；未知 slug / 路径穿越 → 404） |
| GET | `/index` | 索引条目（扁平 entries 列表，每项 type/title/slug；index.md 缺失则回退派生） |
| GET | `/search?q=&top_k=` | BM25 检索（返回 query/total/hits；空 q → 400；snippet ≤500 字，body ≤2000 字 + 截断标记） |

参数约束：`page≥1`（默认 1）、`page_size` 1-200（默认 50）、`top_k` 1-50（默认 10），越界由 Pydantic 返回 422。

环境变量：`WIKI_ROOT`（覆盖默认 wiki 目录；与 CLI 的 `kb search` 一致）。

架构（方案 A，DRY）：`service/store.py`（`load_store` 读 wiki → WikiStore）+ `service/search.py`（BM25+RRF+snippet）+ `service/app.py`（FastAPI 6 路由 + Pydantic 出口模型）。CLI 的 `kb search` 与 REST 的 `/search` 调用同一检索层，不重复逻辑。每请求 `load_store` 重建，无缓存（P0 语料小，够用）。

> 检索机制对 L2 透明：`/search` 现为 BM25，未来可换混合检索（+向量），但端点契约不变。

---

## 后续计划

按 [PRD](docs/superpowers/specs/) 里程碑推进：

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| **M1** | 清洗 pipeline（PDF/Word/Excel/MD → MD → section 切分） | ✅ 完成 |
| **M2** | wiki 归纳层（LLM 两步归纳 + ingest-cache + BM25 检索） | ✅ 完成 |
| **M3** | 增量摄入与自更新闭环（hash.json 三态 + ingest_log + lint + rebuild） | ✅ 完成 |
| **M4** | L1 只读 REST API（`/categories` `/documents` `/search` `/documents/{id}` `/index` `/health`） | ✅ 完成 |
| **M5** | L2 pi Agent（5 工具循环 + 自评重试 + OpenAI 兼容端点） | ⏳ |
| **M6** | L3 Open WebUI 集成（流式 + 引用渲染） | ⏳ |

**M5 要点**：在 M4 只读 REST 之上构建 L2 pi Agent —— 5 工具（list_categories/list_documents/grep_docs/read_section/grade_relevance）薄封装 L1 API，Agent 自主多跳 + 自评重试，暴露 OpenAI 兼容端点供 L3 调用。L1→L2 契约已由 M4 固化（6 个只读 GET 端点）。

**已明确砍掉**：`kb watch` 常驻监听（M3 改手动 loop）；向量检索（P0 阶段先用 BM25，够用再上）。

---

## 设计依据

- [CLAUDE.md](CLAUDE.md) —— 项目硬约束与开发约定
- [docs/architecture_3layer.md](docs/architecture_3layer.md) —— 三层架构
- [docs/kb_retrieval_solutions.md](docs/kb_retrieval_solutions.md) —— 检索方案调研
- [docs/superpowers/specs/](docs/superpowers/specs/) —— 各里程碑设计稿
- [docs/superpowers/plans/](docs/superpowers/plans/) —— 实现计划

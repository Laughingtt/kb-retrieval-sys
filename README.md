# kb-retrieval-sys

企业内部知识库检索系统 —— 把 ~1000 份 PDF / Word / Excel / Markdown 文档清洗成结构化 markdown，归纳成可检索的知识 wiki，对外提供只读检索 API（供后续 L2 Agent 调用）。

> 设计文档：[docs/architecture_3layer.md](docs/architecture_3layer.md)（三层架构）、[docs/kb_retrieval_solutions.md](docs/kb_retrieval_solutions.md)（检索方案调研）、[docs/superpowers/specs/](docs/superpowers/specs/)（里程碑设计稿）。

---

## 架构（三层）

| 层 | 职责 | 技术 | 状态 |
| --- | --- | --- | --- |
| **L1 知识库层** | PDF→MD 清洗 + wiki 归纳 + 增量摄入 + BM25 检索 + 自检/重建 | Python / Click / OpenAI 兼容 LLM | ✅ 已完成（M1–M3） |
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
│   ├── service/               # M4 只读 REST API（待实现）
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
[#1] score=0.8421  data_table_order_detail__a3f9c1e2 / s1
     | order_id | customer |
     | O1       | 张三     |
     [sources]
```

> 当前检索机制对 L2 透明：`/search` 现为 BM25，未来可换混合检索，但端点契约不变。

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

## 后续计划

按 [PRD](docs/superpowers/specs/) 里程碑推进：

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| **M1** | 清洗 pipeline（PDF/Word/Excel/MD → MD → section 切分） | ✅ 完成 |
| **M2** | wiki 归纳层（LLM 两步归纳 + ingest-cache + BM25 检索） | ✅ 完成 |
| **M3** | 增量摄入与自更新闭环（hash.json 三态 + ingest_log + lint + rebuild） | ✅ 完成 |
| **M4** | L1 只读 REST API（`/categories` `/documents` `/search` `/documents/{id}` `/index` `/health`） | ⏳ 下一步 |
| **M5** | L2 pi Agent（5 工具循环 + 自评重试 + OpenAI 兼容端点） | ⏳ |
| **M6** | L3 Open WebUI 集成（流式 + 引用渲染） | ⏳ |

**M4 要点**：把 L1 的检索能力封装成只读 REST 服务（FastAPI），无写入/执行端点，供 L2 pi Agent 调用。检索机制对 L2 透明（现为 BM25，未来可换混合检索，端点契约不变）。

**已明确砍掉**：`kb watch` 常驻监听（M3 改手动 loop）；向量检索（P0 阶段先用 BM25，够用再上）。

---

## 设计依据

- [CLAUDE.md](CLAUDE.md) —— 项目硬约束与开发约定
- [docs/architecture_3layer.md](docs/architecture_3layer.md) —— 三层架构
- [docs/kb_retrieval_solutions.md](docs/kb_retrieval_solutions.md) —— 检索方案调研
- [docs/superpowers/specs/](docs/superpowers/specs/) —— 各里程碑设计稿
- [docs/superpowers/plans/](docs/superpowers/plans/) —— 实现计划

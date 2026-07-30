# P0｜自更新知识检索基础平台 PRD

> 项目：knowledge_agent（企业内部知识库 Agent）
> 阶段：P0｜L1 知识库层落地
> 产物：一个**自更新、可维护、可追溯**的知识检索基础平台
> 关联：[architecture_3layer.md](../../architecture_3layer.md)、[karpathy_wiki_selfbuild_research.md](../../karpathy_wiki_selfbuild_research.md)、[kb_retrieval_solutions.md](../../kb_retrieval_solutions.md)
> 日期：2026-07-30

---

## 一、目标与范围

### 1.1 目标

构建一个**自更新、好维护、全链路可追溯**的本地化知识检索基础平台（L1），为后续 L2 Agent 提供只读检索 API。平台基于 Karpathy LLM-Wiki 原理：知识编译一次、持续复利、维护成本近零。

三个核心诉求（来自用户）：

1. **可追溯**：能看到每份文档从 raw 到被检索命中的完整路径。
2. **可评估**：能验证检索是否准确、有效，并与普通向量知识库对比"更快、更准、更好用"。
3. **自维护**：后续更新与归纳自动化，不靠人盯。

### 1.2 范围（P0 包含）

| 包含 | 不包含（留后续） |
| --- | --- |
| 文档清洗 pipeline（PDF/Word/Excel/MD → MD） | L2 pi Agent（P1） |
| index.json 生成（LLM 两步归纳） | L3 Open WebUI 集成（P2） |
| 检索底座（BM25 + 向量 RRF 融合，可插拔） | LLM rerank 重排（P1/P2） |
| 自更新闭环（增量摄入 + 变更检测 + Lint + 可重建） | 答案回填 wiki（P3 可选，需人工审核） |
| 只读 REST API + CLI | 周期 LLM Lint（矛盾/过时检测，P1） |
| 评估体系（vs 纯向量库对比） | 多用户权限隔离（P1） |

### 1.3 硬约束（来自 CLAUDE.md，不可违反）

1. **独立项目**：自包含，不依赖仓库其他文件夹。
2. **只读查询，不执行动作**：API/工具边界严格限定为查询/检索/读取，无写入/执行/外部调用端点。
3. **全部自托管**：数据、服务在公司内部运行，LLM 端点走公司内部 OpenAI 兼容服务，不依赖外部 SaaS。
4. **基于 Agent，非工作流**（L2 层，P1）：知识检索由 Agent 自主规划。
5. **框架 = pi**（L2 层，P1）。

> 注：硬约束 4/5 属于 L2，P0 只需保证 L1 提供稳定只读契约供 L2 调用。

### 1.4 技术栈决策汇总

| 决策项 | 结论 | 决策依据 |
| --- | --- | --- |
| L1 语言 | Python（FastAPI 服务 + 摄入脚本同语言） | 文档清洗库生态最成熟；摄入/服务复用清洗逻辑；L2 用 TS/pi 经 HTTP 解耦无影响 |
| 时序日志 | 保留 `ingest_log.jsonl`（append-only 文件态） | 零依赖、git 可追踪、自更新闭环依据；P0 不引入数据库 |
| index 生成 | LLM 两步生成（摘要/关键词/章节锚点/related_docs） | index 含金量直接决定 L2 召回质量；章节锚点是 read_section 前提 |
| 检索底座 | BM25(jieba) + bge-m3 向量 + RRF 融合 | BM25 抓精确词（字段名/编号），向量抓语义，互补 |
| 部署形态 | bge-m3 进程内嵌入，内存索引 + 文件持久化 | 1000 份规模内存够用；零外部服务；升级路径清晰（→LanceDB/Qdrant） |
| 运行设备 | CPU（无 GPU 依赖） | 部署门槛低；首次建索引慢可接受 |
| 清洗架构 | 统一 `BaseCleaner` 接口 + 按扩展名分发 | 统一抽象，易扩展 |
| Word 清洗 | Pandoc | 转 markdown 质量最好 |
| 检索粒度 | section 级 | 检索单元=索引单元=加载单元，三层一致 |
| 检索底座结构 | Retriever 接口 + 多实现 + RRF 融合器（可插拔） | 契约不变、内部可演进；P0 单路也能跑 |
| 自更新触发 | `kb watch` 文件监听 + `kb ingest`/`kb lint` 手动命令 | 自动化够用、可控 |

> ⚠️ **待修文档不一致**：`architecture_3layer.md` 第 16 行写"TypeScript/Node 服务"，本 PRD 明确为 Python/FastAPI；第 63 行 `assets/` 目录、第 235 行"多模态图片提取+视觉描述"应删除（无图片场景）。属已知待修，不阻塞 P0。

---

## 二、全局架构与检索流程

### 2.1 分层视图

平台分两条流水线：**离线摄入流水线**（生成知识产物）与**在线检索服务**（提供查询），共享 `knowledge_base/` 文件态存储。

```
┌─────────────────────────── 离线摄入流水线（自更新闭环）───────────────────────────┐
│                                                                                   │
│   raw/ ──变更检测──▶ Cleaner ──▶ md/ ──▶ IndexBuilder(LLM两步) ──▶ index.json    │
│        (文件监听)    (按类型分发)         (摘要/关键词/锚点/关联)                    │
│                                              │                                    │
│                                              ├──▶ 向量索引(vectors.npy)            │
│                                              └──▶ ingest_log.jsonl (append)       │
│                                                                                   │
│   Lint(确定性脚本) ──周期/手动──▶ lint_report.json (孤儿页/缺链接/格式/数据缺口)    │
└───────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼ (共享文件态)
┌─────────────────────────── 在线检索服务（只读 REST + CLI）─────────────────────────┐
│                                                                                   │
│   /search ──▶ RRFFuser ──┬──▶ BM25Retriever ──▶ section 级候选                    │
│             (RRF融合)     └──▶ VectorRetriever ─▶ section 级候选  (可插拔,可缺)   │
│                          ──▶ top_k 结果(doc_id+section_id+snippet+score)          │
│                                                                                   │
│   /index /categories /documents /documents/{id} /health ──▶ index.json + md/      │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 检索路径全链路（可追溯核心）

每份文档从原件到被命中的完整坐标，全程可回溯到 raw 原件。这是平台区别于黑盒 RAG 的关键。

```
raw/order_detail.xlsx                      ← 唯一真相源(不可变)
  │  [清洗] PyMuPDF4LLM/pdfplumber/python-docx+Pandoc/openpyxl
  ▼
md/data_table/order_detail.md              ← 清洗产物(section 切分, 保留表格)
  │  [归纳] LLM 两步: 识别类型/实体/关联 → 生成摘要/关键词/锚点/related
  ▼
index.json::documents[doc_id]              ← 导航核心
  │  doc_id = data_table__order_detail__001
  │  sections = [{section_id, title, line_start, line_end}]
  │  related_docs = [...]
  │  [索引] BM25 倒排(over md sections) + 向量(bge-m3 over sections)
  ▼
检索索引 (section 级)                       ← 检索单元 = 索引单元 = 加载单元
  │  [查询] /search?q=order_id → RRF 融合 → top_k
  ▼
命中结果: doc_id + section_id + snippet + score
  │  [加载] /documents/{id}?section=s0 → 按行号切片返回该段
  ▼
CLI: kb search "order_id" → 命中段 + 来源路径 + 分数
```

**可追溯命令**：`kb trace <doc_id>` 打印该文档在管线各环节的状态（raw 存在性、md 生成时间、index 条目、向量就绪性、最近一次摄入/lint 记录）。

### 2.3 三大操作（Karpathy Ingest/Query/Lint 落地）

| Karpathy 操作 | 本项目落点 | 自动化程度 |
| --- | --- | --- |
| **Ingest** | 离线摄入流水线：变更检测→清洗→LLM两步→index/向量→log | `kb watch` 自动 / `kb ingest` 手动 |
| **Query** | 在线检索服务 `/search` + CLI | 在线实时 |
| **Lint** | 确定性脚本检查（P0）+ 周期 LLM 检查（P1） | `kb lint` 手动 / CI 跑 |

---

## 三、数据模型

全文件态，零数据库，git 可追踪。

```
l1_kb/
├── knowledge_base/                    # 数据(生成物 + 原件)
│   ├── raw/                           # 原始文档(不可变,只读,真相源)
│   │   ├── data_product/              # 数据产品:接口文档/产品介绍
│   │   ├── process/                   # 公司流程制度
│   │   └── data_table/                # 数据表字段说明
│   ├── md/                            # 文档→MD 清洗结果(保留表格/版式)
│   │   ├── data_product/{api_docs,intro}/
│   │   ├── process/
│   │   └── data_table/
│   ├── index.json                     # 全局目录(标题/摘要/关键词/章节锚点/related_docs)
│   ├── ingest_log.jsonl               # 摄入时序日志(append-only, 可 grep)
│   ├── hash.json                      # 变更检测:每份 raw 文档的哈希
│   ├── vectors.npy                    # section 向量(bge-m3, 内存加载+落盘)
│   ├── vector_meta.json               # 向量元数据(section_id ↔ 向量行号)
│   └── lint_report.json               # 最近一次 lint 报告
├── ingest/                            # 摄入脚本(python)
├── service/                           # 检索 API 服务(FastAPI)
└── cli/                               # CLI 工具
```

### 3.1 raw 不可变原则

- `raw/` 是唯一真相源，**LLM/服务只读不写**。
- `md/`、`index.json`、`vectors.npy`、`ingest_log.jsonl` 全是 raw 的**生成物**，可随时从 raw 重建（见 §7.4 可重建性）。

---

## 四、清洗 pipeline

### 4.1 架构：BaseCleaner + 按扩展名分发

```
clean(path) → dispatcher(按扩展名) → XxxCleaner.to_markdown() → md 文本
```

```python
class BaseCleaner:
    def to_markdown(self, raw_path: Path) -> str:
        """返回清洗后的 markdown, 内含 section 切分(标题层级)."""
        raise NotImplementedError

class PdfCleaner(BaseCleaner): ...      # PyMuPDF4LLM.to_markdown + pdfplumber.extract_tables
class WordCleaner(BaseCleaner): ...     # Pandoc 转换(docx→md, ATX标题+pipe表)
class ExcelCleaner(BaseCleaner): ...    # openpyxl+pandas: 每 sheet → 完整 markdown 表
class MarkdownCleaner(BaseCleaner): ... # 原样保留

CLEANERS = {".pdf": PdfCleaner, ".docx": WordCleaner, ".xlsx": ExcelCleaner, ".md": MarkdownCleaner}
```

### 4.2 各类型清洗要点

| 类型 | 工具 | 关键能力 | 要点 |
| --- | --- | --- | --- |
| **PDF** | PyMuPDF4LLM + pdfplumber | 保留表格→markdown 表 | 表格是数据表/接口文档核心,必须完整转 markdown 表 |
| **Word** | Pandoc | ATX 标题 + pipe 表 | 流程制度文档,保留标题层级 |
| **Excel** | openpyxl + pandas | **每个 sheet → 完整 markdown 表(含表头)** | **重中之重**:字段说明表必须整表转 markdown,BM25 才能精准召回字段名 |
| **Markdown** | 原样 | — | 已是目标格式 |

### 4.3 Excel 多 sheet = 多 section

每个 sheet 转成一个 markdown 表,作为该文档下的一个 section（对应决策：每个 sheet = 一个 section）。这样 `read_section(doc_id, sheet名)` 能精准取一个表。

### 4.4 section 切分

清洗产出的 markdown 按 `#`/`##` 标题切分 section。**section 是最小检索单元**。行号范围由脚本解析标题行号确定（确定性,不靠 LLM）。

---

## 五、index.json schema

L1 导航核心,Agent 查询入口。LLM 两步归纳生成。

```json
{
  "version": "1.0",
  "indexed_at": "2026-07-30T00:00:00",
  "documents": [
    {
      "doc_id": "data_table__order_detail__001",
      "title": "订单明细表字段说明",
      "category": "data_table",
      "source_path": "raw/data_table/order_detail.xlsx",
      "md_path": "md/data_table/order_detail.md",
      "summary": "LLM 生成的 3-5 句摘要",
      "keywords": ["订单", "order_id", "字段说明"],
      "ingested_at": "2026-07-30",
      "sections": [
        {
          "section_id": "s0",
          "title": "Sheet1: 订单主表",
          "line_start": 1,
          "line_end": 48,
          "level": 2
        }
      ],
      "related_docs": ["data_table__order__002"]
    }
  ]
}
```

### 5.1 字段说明

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `doc_id` | 脚本生成 | `分类__文件名(去扩展名)__序号`;稳定 ID,增量更新依据 |
| `title` | LLM | 文档标题 |
| `category` | LLM 第1步 | data_product / process / data_table |
| `summary` | LLM 第2步 | 3-5 句摘要 |
| `keywords` | LLM 第2步 | 检索辅助 |
| `sections.line_start/end` | **脚本回填** | 解析 markdown 标题行号,LLM 不参与(避免数错行) |
| `related_docs` | LLM 第1步 | 关联文档 doc_id 列表(非 Obsidian wikilink) |
| `ingested_at` | 脚本 | 摄入时间戳 |

### 5.2 LLM 两步归纳

```
LLM 第1步 分析: 识别 文档类型 / 关键实体 / 所属分类 / 关联文档(related_docs)
LLM 第2步 生成: 摘要 / 关键词 / 章节标题
脚本回填:       sections.line_start/end (解析 markdown 标题行号)
→ 更新 index.json (按 doc_id 增量更新该条)
```

### 5.3 `/index` 端点

返回**全量** index.json（不过滤）。理由：index 价值在"一次读完全局导航",过滤破坏此用法。过滤由 L2 `list_documents` 工具负责。1000 份文档 index 约 几百KB~1MB,可一次返回。

---

## 六、检索底座（可插拔）

### 6.1 结构：Retriever 接口 + 多实现 + RRF 融合器

兑现 `architecture_3layer.md` 第 83 行"检索机制对 L2 透明、内部可演进、契约不变"。

```python
class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, top_n: int) -> list[SearchHit]:
        """返回 section 级候选: {doc_id, section_id, snippet, score, source: 'bm25'|'vector'}"""

class BM25Retriever(Retriever):    # jieba 分词 + rank-bm25, over md sections
    ...

class VectorRetriever(Retriever):  # bge-m3 向量 + 余弦相似, over section 向量
    ...  # P0 可缺省:环境未就绪时不注册,/search 退化为单路 BM25

class RRFFuser:
    def fuse(self, results: list[list[SearchHit]], k=60, top_k=10) -> list[SearchHit]:
        """RRF: score = Σ 1/(k + rank_i); section 级去重(同 section 取最高分)"""
```

### 6.2 RRF 参数

| 参数 | 值 | 说明 |
| --- | --- | --- |
| k(平滑常数) | 60 | 业界标准 |
| 每路候选 top_n | 50 | 1000 份规模足够覆盖相关项 |
| 最终 top_k | 10(默认,`?top_k=` 可调) | Agent 多跳够用 |
| 去重粒度 | section 级 | 同一 section 只保留最高分;同文档多 section 可并存 |

### 6.3 P0 运行形态

- **测试/验证阶段**：仅 BM25 单路（向量环境未装），RRF 单路直通。**全局框架完整可跑**。
- **向量就绪后**：注册 VectorRetriever，自动变两路 RRF 融合。**不动 `/search` 外部契约**。

> 这满足用户"测试时不用装向量环境、先看全局"的诉求：框架完整,向量是可插入增强件。

### 6.4 为什么比普通向量库"更快更准更好用"

| 维度 | 普通向量库 | 本平台 | 优势来源 |
| --- | --- | --- | --- |
| 精确词召回 | 弱(字段名 order_id 未必与"订单ID"对齐) | **强**(BM25 精确匹配) | BM25 |
| 语义召回 | 强 | **强**(bge-m3) | 向量 |
| 综合 | 单路盲区 | **两路互补** | RRF 融合 |
| 返回粒度 | 整篇文档 | **section 级精准片段** | section 切分 |
| 下游成本 | LLM 啃全文 | **LLM 只读命中段** | read_section 按需加载 |

**核心优势不是检索算法本身,而是"section 级精准召回 + 按需加载"**：少喂给 LLM、少往返,端到端更快更准。详见 §10 评估体系验证。

---

## 七、自更新与维护（Karpathy 原理落地）

本章是平台"自更新、好维护"的核心,与检索能力并列为一等公民。

### 7.1 增量摄入

raw/ 加新文档或改旧文档时,**只重处理那一份**,不全量重建。

```
检测变更(见 7.2) → 清洗该文档 → LLM 两步 → 更新该 doc 的 index 条目 + 向量 + 追加 log
```

按 `doc_id` 增量更新 index.json：存在则覆盖该条,不存在则追加。向量同步更新该 doc 的 section 向量。

### 7.2 变更检测

`hash.json` 记录每份 raw 文档的内容哈希。

```json
{"data_table__order_detail__001": {"hash": "sha256...", "path": "raw/data_table/order_detail.xlsx", "ingested_at": "2026-07-30"}}
```

摄入时比对：哈希不变 → 跳过;变了或新增 → 重摄入。

### 7.3 Lint 自检（确定性脚本,P0）

| 检查项 | 方法 | 严重度 |
| --- | --- | --- |
| 孤儿页 | index.json 中无任何 related_docs 指向的文档 | warn |
| 缺交叉引用 | 两文档关键词高度重叠但互无 related_docs | warn |
| 格式校验 | ingest_log.jsonl 每行可 grep 解析;index.json schema 合法 | error |
| 数据缺口 | 某分类下文档数异常少(如 data_table 仅 3 份) | info |

输出 `lint_report.json`,可 CI 跑。**周期 LLM Lint（矛盾/过时/缺概念页）放 P1**。

### 7.4 可重建性

`md/`、`index.json`、`vectors.npy`、`ingest_log.jsonl` 全是 raw 的生成物。`kb rebuild` 可从 raw + hash.json 完整重建所有生成物（清空生成物 → 全量重摄入）。这是 Karpathy "raw 是唯一真相源"的兜底。

### 7.5 自更新触发

| 方式 | 命令 | 场景 |
| --- | --- | --- |
| 文件监听(自动) | `kb watch` | 常驻监听 raw/ 变更,自动增量摄入 |
| 手动摄入 | `kb ingest <path>` | 指定文档/目录摄入 |
| 手动 Lint | `kb lint` | 触发确定性检查 |
| 全量重建 | `kb rebuild` | 生成物损坏时从 raw 重建 |

### 7.6 ingest_log.jsonl 格式

append-only,每行一条,可 grep 解析。

```json
{"ts": "2026-07-30T10:00:00", "type": "ingest", "doc_id": "data_table__order_detail__001", "title": "订单明细表字段说明"}
{"ts": "2026-07-30T10:05:00", "type": "lint", "issues": 3}
```

grep 示例：`grep '"type":"ingest"' ingest_log.jsonl | tail -5` 看最近 5 次摄入。

---

## 八、API 契约（只读 REST）

L2 调用入口。**全部只读,无写入/执行端点**(守硬约束)。

| 端点 | 方法 | 对应能力 | 返回 |
| --- | --- | --- | --- |
| `/categories` | GET | list_categories 浏览分类 | `[{id,name,doc_count}]` |
| `/documents?category=&kw=` | GET | list_documents 列候选文档 | `[{id,title,summary,path}]` |
| `/documents/{id}` | GET | read_document / read_section(支持 `?section=`) | markdown 全文/章节 |
| `/search?q=&top_k=` | GET | grep_docs 混合检索 | `[{doc_id,section_id,title,snippet,score}]` |
| `/index` | GET | 取全量 index.json | index 对象 |
| `/health` | GET | 健康检查 | `{status,doc_count,indexed_at,vector_ready}` |
| `/trace/{doc_id}` | GET | 文档检索路径全链路 | `{raw_exists,md_path,indexed,vector_ready,logs}` |

**契约稳定性**：`/search` 内部从 BM25 升级为 BM25+向量+RRF,端点不变,L2 无感。

---

## 九、CLI

### 9.1 命令

```bash
kb categories                                    # 列分类
kb documents --category data_table               # 列文档
kb search "order_id" [--top_k 10]                # 检索(核心验收)
kb read <doc_id> [--section <section_id>]        # 读文档/章节
kb index                                         # 打印 index 概览
kb trace <doc_id>                                # 打印检索路径全链路
kb ingest <path>                                 # 手动摄入
kb watch                                         # 监听 raw/ 自动增量摄入
kb lint                                          # 跑确定性 Lint
kb rebuild                                       # 从 raw 全量重建
```

### 9.2 输出格式

`kb search` 每条结果：

```
[#1] score=0.0312  data_table__order_detail__001 / s0
     Sheet1: 订单主表
     | order_id | string | 订单唯一标识 |
     [md: md/data_table/order_detail.md:1-48]
```

---

## 十、评估体系（vs 纯向量库对比）

验证"更快、更准、更好用"。可量化对比,不嘴上说。

### 10.1 对比对象

同等条件下的**纯向量库**（bge-m3 + 余弦相似,文档级返回）。

> **分阶段说明**：P0 测试阶段不装向量环境,只用 BM25 单路跑通框架（见 §6.3、§11）。§10 的完整对比评估在**向量环境就绪后**运行;P0 验收（§11）只要求 BM25 路通过,不依赖向量。这样"先看全局框架"与"最终量化对比"分两步,互不阻塞。

### 10.2 指标

| 维度 | 指标 | 测法 | 预期本平台 vs 纯向量库 |
| --- | --- | --- | --- |
| 准确率 | top_k 内命中正确 section 比例 | 标注用例集 | **≥** (两路互补) |
| 召回率 | 该命中的有没有漏 | 标注用例集 | **≥** |
| 精确词召回 | 字段名/编号 top_5 命中率 | 精确词用例 | **>** (BM25 主场) |
| 查询延迟 | 单次查询 ms | 计时 | 单路 BM25 最快;两路略慢但毫秒级 |
| 下游 token | 返回内容 token 数 | 统计 | **<** (section 级 vs 全文) |

### 10.3 核心优势论断（待验收验证）

> "更快更准更好用"的核心**不是检索算法本身,而是 section 级精准召回 + 按需加载**：少喂 LLM、少往返,端到端更快;BM25 补精确词盲区,更准。

### 10.4 评估脚本

`kb eval`：跑标注用例集,输出对比报告（本平台 vs 纯向量库各项指标）。

---

## 十一、验收

### 11.1 验收数据

采用 **合成样本 + 真实数据复验** 两步：

1. **合成样本**（不阻塞）：造 5-10 份合成文档（含字段说明表/流程编号/语义近义词），跑通三类用例。证明 pipeline 机制正确。
2. **真实数据复验**：用户提供真实文档后,换数据复验质量。

### 11.2 验收用例（合成样本阶段）

| 用例 | 查询 | 期望 | 验证能力 |
| --- | --- | --- | --- |
| 精确词召回 | `kb search "order_id"` | top_5 命中含 order_id 字段的 section,snippet 含该字段行 | BM25 精确召回(P0 硬指标) |
| 流程编号召回 | `kb search "PRC-2024-003"` | top_5 命中含该编号的流程文档 section | BM25 精确召回(P0 硬指标) |
| 语义召回 | `kb search "订单状态"` | top_5 命中含"交易进展/订单状态"的 section(未必有原词) | 向量语义召回(向量就绪后) |

**通过判据**：前两类（精确召回）top_5 命中正确 section 为 P0 必过项;第三类在向量就绪后验证。

### 11.3 P0 完成判定

- [ ] 清洗 pipeline 四类文档正确转 MD(表格/标题层级保留)
- [ ] index.json schema 合法,LLM 两步归纳生成
- [ ] `/search` BM25 单路可跑,返回 section 级结果
- [ ] 检索底座可插拔结构就位(VectorRetriever 预留)
- [ ] 增量摄入 + 变更检测 + Lint + 可重建 全部可用
- [ ] `kb trace` 能打印文档全链路
- [ ] 合成样本三类用例通过(精确召回必过)
- [ ] API 全部只读,无写入/执行端点

---

## 十二、一句话

P0 交付一个**自更新、可维护、可追溯**的本地化知识检索基础平台：raw 不可变 + LLM 两步归纳生成 index + BM25/向量 RRF 可插拔检索 + 增量摄入/Lint/可重建自维护闭环 + 全链路可追溯 + 评估对比体系。它不是一次性建好的死库,而是按 Karpathy 原理持续复利、维护成本近零的活地基——为 P1 L2 Agent 提供稳定只读契约。

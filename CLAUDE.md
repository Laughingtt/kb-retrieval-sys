# knowledge_agent — 企业内部知识库 Agent

本项目是一个**独立项目**，为业务人员提供基于 ~1000 份 PDF 文档（数据产品/API 文档、公司流程制度、数据表字段说明）的对话式知识查询能力。

> 关联设计文档：[docs/architecture_3layer.md](docs/architecture_3layer.md)（三层架构）、[docs/kb_retrieval_solutions.md](docs/kb_retrieval_solutions.md)（检索方案调研）。

---

## 一、硬约束（不可违反）

1. **独立项目**：本目录是自包含项目。**不要查看、扫描、依赖仓库其他文件夹**（如 llm_gateway、openwebui、deploy、explorer-demo 等）。所有依赖在本目录内声明、在本目录内搭建。
2. **仅文档查询，不执行动作**：Agent 的工具边界严格限定为"查询/检索/读取文档"。**绝不**实现写文件、调外部系统、执行命令、发邮件等任何操作类工具。
3. **全部自托管**：所有数据、服务在公司内部运行。LLM 端点走公司内部 OpenAI 兼容服务（可配置），不依赖外部 SaaS。
4. **基于 Agent，非工作流**：知识检索由 Agent 自主规划（多跳 + 自我判断重试），不是固定流水线编排。
5. **框架 = pi**：L2 Agent 层使用 [pi](https://github.com/earendil-works/pi)（TypeScript agent toolkit）。

## 二、三层架构

| 层   | 职责  | 技术  |
| --- | --- | --- |
| **L1 知识库层** | 知识归纳整理 + 对外提供只读检索 API/CLI（PDF→MD + index.json + BM25 检索） | 待定（服务 + 摄入脚本） |
| **L2 Agent 层** | 拆解问题、多跳检索编排、自评重试、带引用总结返回；暴露 OpenAI 兼容端点 | TypeScript / pi |
| **L3 交互层** | 用户提问、对话、展示带来源引用的答案 | Open WebUI |

**层间契约**（稳定，内部演进不破坏）：

- L3 → L2：OpenAI 兼容 `/v1/chat/completions`
- L2 → L1：只读 REST API（`/categories` `/documents` `/search` `/documents/{id}` `/index` `/health`），**无写入/执行端点**
- L2 → LLM：OpenAI 兼容端点（可配置 base URL / key / model）

## 三、目录结构（规划）

```
knowledge_agent/
├── CLAUDE.md                      # 本文件
├── docs/                          # 设计文档
│   ├── architecture_3layer.md
│   └── kb_retrieval_solutions.md
├── l1_kb/                         # L1 知识库层
│   ├── ingest/                    # PDF→MD 清洗 + index.json 生成
│   ├── service/                   # 检索 API 服务
│   └── knowledge_base/            # 数据：raw/ md/ index.json assets/
├── l2_agent/                      # L2 pi Agent 服务
├── l3_ui/                         # L3 Open WebUI 部署配置
└── docker-compose.yml             # 整体编排（可选）
```

## 四、落地顺序

- **P0｜L1 知识库层**（先建，最自包含、可独立验证）：PDF→MD 清洗 pipeline + index.json + BM25 检索 API。验收：CLI 能对文档精准召回字段名/流程编号。
- **P1｜L2 pi Agent**（依赖 L1 API）：pi 工具循环 + 5 工具（list_categories/list_documents/grep_docs/read_section/grade_relevance）+ 自评重试 + OpenAI 兼容端点。验收：多跳问题能跨文档取全、带引用返回。
- **P2｜L3 集成 + 打磨**：Open WebUI 接入 kb-agent 连接；流式 + 引用渲染。

## 五、开发约定

- 写代码前先确认设计文档与本文件不冲突；冲突时以本文件硬约束为准。
- L1 检索机制对 L2 透明：`/search` 当前为 BM25，未来可换混合检索，但端点契约不变。
- 工具一律薄封装 L1 API；Agent 工具只读，不新增操作类能力。
- 提交前验证：L1 用 CLI 独立验证检索质量；L2 验证多跳取全 + 带引用。

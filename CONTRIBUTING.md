# 贡献指南 — kb-retrieval-sys

感谢参与本企业知识库检索系统！本文档说明开发约定与提交规范。

## 一、项目定位与硬约束（不可违反）

本项目是**自包含的独立项目**，仅做**文档查询**，不执行任何动作。贡献代码前请先阅读
[`CLAUDE.md`](./CLAUDE.md) 的「硬约束」与[`docs/architecture_3layer.md`](./docs/architecture_3layer.md)
的三层架构契约。要点：

1. **独立项目**：不依赖、不扫描仓库其他文件夹。所有依赖在本目录内声明。
2. **只读边界**：Agent 工具严格只读（查询/检索/读取文档），**绝不**实现写文件、调外部系统、
   执行命令、发邮件等操作类工具。L1 摄入脚本写 md/wiki 属正常离线流程，不受此限。
3. **全部自托管**：所有数据/服务在公司内部运行；LLM 走公司内部 OpenAI 兼容服务（可配置）。
4. **层间契约稳定**：
   - L3 → L2：OpenAI 兼容 `/v1/chat/completions`
   - L2 → L1：只读 REST API（`/categories` `/documents` `/search` `/documents/{id}` `/index` `/health`），
     **无写入/执行端点**
   - L2 → LLM：OpenAI 兼容端点（可配置 base URL / key / model）
   - L1 检索机制对 L2 透明：`/search` 当前 BM25，未来可换混合检索，端点契约不变。

## 二、GPL 红线

本项目借鉴 Karpathy / llm_wiki 等**方法论**，但**绝不 import 或复制 GPL 源码**。
若某实现依赖 GPL 库，需改用同等能力的宽松许可（Apache-2.0 / MIT / BSD）替代，
或在贡献说明中明确隔离边界。提交前自查依赖许可。

## 三、开发环境

```bash
# Python >=3.12
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # 安装项目 + 测试依赖（reportlab/httpx/pytest）

# 验证 CLI 可用
kb --help
python -m kb_retrieval.kb.cli.kb --help
```

## 四、测试

```bash
# 默认单测（跳过 e2e）
python -m pytest -q

# 端到端（需起真实 KB Service + 真 LLM key，marker e2e）
DEEPSEEK_API_KEY=*** python -m pytest -m e2e
```

- 单测必须 mock L1 / LLM，**真 key 绝不写进任何文件**（见 [SECURITY.md](./SECURITY.md)）。
- e2e 才用真 key，从环境变量读取。
- 提交前确保 `python -m pytest -q` 全绿（当前基线 232 passed / 3 deselected）。

## 五、提交规范

- 分支命名：`feat/<topic>` / `fix/<topic>` / `refactor/<topic>` / `docs/<topic>`。
- Commit message 前缀：`feat` / `fix` / `refactor` / `docs` / `test` / `chore`，
  中文描述可，例：`refactor: 重命名 l1_kb→kb_retrieval.kb 开源目录结构`。
- 一个 PR 聚焦一件事；重构与功能改动分开提交。
- 改动涉及 API/契约变更时，同步更新 [`docs/architecture_3layer.md`](./docs/architecture_3layer.md)
  与 [`README.md`](./README.md) 的端点/路径说明。

## 六、目录结构约定

单一顶层包 `kb_retrieval/`，下含 `kb/`（知识库层）与 `agent/`（Agent 层）两个语义化子包。
详见 [README.md](./README.md) 目录树。新增模块请落入对应子包，保持薄封装 + 相对 import 风格。

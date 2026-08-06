# 变更日志 — kb-retrieval-sys

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。 notable 变更记录于本文件。

## [Unreleased]

### 重构 — 开源项目化目录结构 (2026-08)

消除内部层名 `l1_kb` / `l2_agent`，按开源 Python 项目标准重组目录：

- 单一顶层包 `kb_retrieval/`，下含语义化子包 `kb/`（原 `l1_kb/`，知识库层）与
  `agent/`（原 `l2_agent/`，Agent 层）。flat layout + hatchling 后端。
- `agent/l1_client.py` → `agent/kb_client.py`；类 `L1Client` → `KBClient`、
  `L1Error` → `KBClientError`；环境变量 `L1_BASE_URL` → `KB_BASE_URL`、
  `L1_TIMEOUT` → `KB_TIMEOUT`。
- `kb_retrieval/kb/config.py`：`_PROJECT_ROOT` 由 `parents[1]` 改为 `parents[2]`
  （config 随目录深一层）；3 处硬编码路径前缀 `l1_kb` → `kb_retrieval/kb`。
- `pyproject.toml`：`packages=["kb_retrieval"]`；3 个 console script 指向新模块路径；
  `testpaths` 指向 `kb_retrieval/agent/tests`。
- 新增开源配套文件：`LICENSE`（Apache-2.0）、`CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`。
- `.gitignore` 路径前缀同步更新；补 `dist/`、`build/`。
- 全量 64 处相对 import 无需改动（flat + 子包方案关键收益）；绝对 import 机械替换。
- 验证基线持平：232 passed / 3 deselected。

> 说明：架构层概念 L1/L2/L3 仍保留在 `docs/architecture_3layer.md` 与 CLAUDE.md 作为
> 设计词汇（指知识库层 / Agent 层 / 交互层），仅消除**路径与模块名**中的层名。

### 历史

- **M5**：L2 Python Agent 完成（工具循环 + 5 工具 + 自评重试 + OpenAI 兼容端点）。
- **M4**：L1 KB Service 检索 API（BM25 + RRF + 向量）。
- **M3**：L1 增量摄入与自更新闭环（add/modify/delete + lint）。
- **M1–M2**：L1 PDF/Word/Excel→MD 清洗 pipeline + index.json + 配置。

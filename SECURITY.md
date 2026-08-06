# 安全说明 — kb-retrieval-sys

## 一、密钥绝不落盘

本项目的 LLM API key（如 DeepSeek key）**只在运行时从环境变量读取，绝不写进任何文件**：

- 配置模块 `kb_retrieval/agent/config.py` 与 `kb_retrieval/kb/config.py` 只用 `os.environ` 取 key，
  **不引入 `python-dotenv`**，不读 `.env`。
- 单元测试一律 **mock** L1 / LLM，不触碰真 key。
- 仅 e2e 测试（`pytest -m e2e`）使用真 key，且 key 必须从环境变量传入
  （`DEEPSEEK_API_KEY=*** python -m pytest -m e2e`），不得写入脚本、配置、用例或文档。

## 二、报告安全问题

发现安全漏洞（密钥泄露、注入、越权访问、只读边界被绕过等）请**不要**公开 issue，
联系仓库维护者私下披露，确认修复后再公开。

## 三、只读边界（架构级安全约束）

Agent 工具严格只读：L2 Agent 暴露给 L1 的调用链中**不存在写入/执行端点**。
若贡献代码引入了任何写文件、调外部系统、执行命令、发邮件的能力，将被视为违反硬约束，
不予合并。详见 [`CLAUDE.md`](./CLAUDE.md) 硬约束 2 与 [`CONTRIBUTING.md`](./CONTRIBUTING.md)。

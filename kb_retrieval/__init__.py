"""kb-retrieval-sys — 企业内部知识库检索系统。

顶层包，含两个语义化子包：

- ``kb_retrieval.kb``    : 知识库层（摄入 + 检索底座 + 只读 REST API）
- ``kb_retrieval.agent`` : Python Agent 层（多跳检索 + 自评重试 + OpenAI 兼容端点）

设计文档：docs/architecture_3layer.md（三层架构）。仅文档查询，不执行动作；
Agent 工具严格只读。LLM 走公司内部 OpenAI 兼容服务，全部自托管。
"""

__version__ = "0.1.0"

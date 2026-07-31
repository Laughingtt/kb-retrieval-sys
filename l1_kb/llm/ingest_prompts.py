"""step1/step2 prompt 构造 —— M2 设计 §3.3/§3.4。

吸收 llm_wiki buildAnalysisPrompt / buildGenerationPrompt 原理（Python 重实现）。
step1 注入当前 index.md（判断实体是否已存在）+ 源文本 → 结构化 JSON。
step2 注入 schema + purpose + index + step1 分析（标注 context only）+ 源文本 → FILE block。
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["build_step1_messages", "build_step2_messages"]

_STEP1_SYSTEM = """你是企业知识库的编目员（cataloger）。阅读一份原件的 markdown，输出结构化分析 JSON。

页类型固定为这 4 类之一：source / entity / concept / process。
- source：一份原件的摘要页（每次摄入必产 1 张）。
- entity：业务实体（数据表、API、系统、角色等业务对象）。
- concept：业务概念（术语、口径、定义）。
- process：流程/制度（审批流、制度编号 PRC-xxx、步骤、责任人、上下游、触发条件）。

只输出 JSON，不要任何额外文字。JSON schema：
{
  "entities": [{"name": "...", "slug": "entity_xxx", "role": "...", "exists": false}],
  "concepts": [{"name": "...", "slug": "concept_xxx", "definition": "...", "exists": false}],
  "processes": [{"name": "...", "slug": "process_xxx", "code": "PRC-xxx", "owner": "...", "steps": ["..."], "upstream": "...", "downstream": "...", "exists": false}],
  "summary": "3-5 句摘要",
  "keywords": ["字段名/编号/术语"]
}

要求：
- slug 用英文小写 + 下划线（如 entity_order_detail）。
- exists：对照下方 Wiki Index 判断该实体/概念/流程是否已存在（已存在则 true，避免重复生成）。
- summary 点到为止；keywords 必须包含字段名、流程编号等可检索关键串。
- 若该原件不含某类，对应数组留空。
- 流程类页（processes 数组）落盘目录为单数 wiki/process/（注意：不是 processes/）。
"""

_STEP2_SYSTEM = """你是企业知识库的 wiki 页生成器。根据 step1 分析 + 源文本，生成 wiki 页。

输出严格使用 FILE block 格式，每个页一个 block：
---FILE: wiki/{sources|entities|concepts|process}/{slug}.md---（process 目录是单数 process，不是 processes）
<frontmatter + body>
---END FILE---

frontmatter 必须含字段（YAML，数组用内联 [a, b]）：
type / title / created / updated / tags / related / sources

规则：
- 必产 1 张 source 摘要页：路径 wiki/sources/{slug}.md，title 为原件标题，body 含关键字段表/摘要。
- 可选若干 entity/concept/process 页（step1 识别出且 exists=false 的才生成）。
- 禁止生成 index.md / log.md / overview.md（由应用确定性维护）。
- sources 必须含当前原件的 source_identity。
- related 用裸 slug（不带 wiki/ .md [[]]）。
- step1 分析是 context only, do not repeat——不要把分析 JSON 原样写进 body。
- title 含中文时用双引号包裹。
"""


def build_step1_messages(source_identity: str, md_text: str, index_md: str) -> tuple[str, str]:
    user = (
        f"当前 Wiki Index（用于判断实体是否已存在）：\n\n{index_md}\n\n"
        f"原件 source_identity: {source_identity}\n\n"
        f"原件 markdown：\n\n{md_text}\n\n"
        f"请输出分析 JSON。"
    )
    return _STEP1_SYSTEM, user


def build_step2_messages(
    source_identity: str, md_text: str, step1_result: dict[str, Any], index_md: str
) -> tuple[str, str]:
    user = (
        f"当前 Wiki Index（context only）：\n\n{index_md}\n\n"
        f"原件 source_identity: {source_identity}\n\n"
        f"step1 分析（context only, do not repeat）：\n\n{json.dumps(step1_result, ensure_ascii=False, indent=2)}\n\n"
        f"原件 markdown：\n\n{md_text}\n\n"
        f"请输出 FILE block（必产 1 张 source 摘要页）。"
    )
    return _STEP2_SYSTEM, user

"""step1/step2 prompt 构造 —— M2 设计 §3.3/§3.4。

system prompt 从 page_types.yaml（registry）渲染类型清单 / step1 JSON schema /
FILE block 路径枚举 / 单数目录锚点——加第 N 类只改 YAML，提示词自动跟随。
吸收 llm_wiki buildAnalysisPrompt / buildGenerationPrompt 原理（Python 重实现）。
step1 注入当前 index.md（判断实体是否已存在）+ 源文本 → 结构化 JSON。
step2 注入 schema + purpose + index + step1 分析（标注 context only）+ 源文本 → FILE block。
"""

from __future__ import annotations

import json
from typing import Any

from ..ingest.wiki.page_type_config import PageTypeSpec, get_registry

__all__ = ["build_step1_messages", "build_step2_messages"]


def _simple_plural(key: str) -> str:
    """简单复数猜想，用于判断 dir 是否不规则。

    辅音+y 结尾 → ies（entity→entities）；其余 → +s（source→sources, concept→concepts）。
    仅为锚点提示服务，无需覆盖所有英语例外。
    """
    if len(key) >= 2 and key.endswith("y") and key[-2] not in "aeiou":
        return key[:-1] + "ies"
    return key + "s"


def _is_irregular_dir(spec: PageTypeSpec) -> bool:
    """dir 不等于简单复数猜想 → 视为不规则（单数/特殊），需锚点提示。"""
    return spec.dir != _simple_plural(spec.key)


def _render_type_list() -> str:
    """渲染 `- {key}：{description}` 清单行（替代手写 4 行）。"""
    r = get_registry()
    return "\n".join(f"- {s.key}：{s.description}" for s in r.types)


def _render_type_keys_slash() -> str:
    """渲染 `source/entity/concept/process` 形式的键枚举。"""
    return "/".join(s.key for s in get_registry().types)


def _render_dir_list_pipe() -> str:
    """渲染 FILE block 路径段的 `{sources|entities|concepts|process}` 枚举。"""
    return "{" + "|".join(s.dir for s in get_registry().types) + "}"


def _render_step1_schema() -> str:
    """渲染 step1 JSON schema 数组键部分（每个 plural_key 非空类型一行）。

    mandatory 类型不进数组（恒 1 张）；其余按 plural_key 生成 `"key": [schema_template]`。
    schema_template 为空时退化为 `[{"name": "...", "exists": false}]`。
    """
    r = get_registry()
    lines = []
    for s in r.types:
        if not s.plural_key:
            continue
        if s.schema_template:
            lines.append(f'  "{s.plural_key}": [{s.schema_template}],')
        else:
            lines.append(f'  "{s.plural_key}": [{{"name": "...", "exists": false}}],')
    return "\n".join(lines)


def _render_dir_anchors() -> str:
    """对 dir 不等于简单复数的类型，生成单数/不规则目录锚点提示。"""
    r = get_registry()
    parts = []
    for s in r.types:
        if _is_irregular_dir(s):
            parts.append(
                f"- {s.key} 类页落盘目录为单数 wiki/{s.dir}/（注意：不是 {_simple_plural(s.key)}/）。"
            )
    if not parts:
        return ""
    return "\n目录约定：\n" + "\n".join(parts)


def _step1_system() -> str:
    type_list = _render_type_list()
    type_keys = _render_type_keys_slash()
    schema_arrays = _render_step1_schema()
    anchors = _render_dir_anchors()
    anchor_block = (anchors + "\n\n") if anchors else ""
    return f"""你是企业知识库的编目员（cataloger）。阅读一份原件的 markdown，输出结构化分析 JSON。

页类型固定为这几类之一：{type_keys}。
{type_list}

只输出 JSON，不要任何额外文字。JSON schema：
{{
{schema_arrays}
  "summary": "3-5 句摘要",
  "keywords": ["字段名/编号/术语"]
}}

要求：
- slug 用英文小写 + 下划线（如 entity_order_detail）。
- exists：对照下方 Wiki Index 判断该实体/概念/流程是否已存在（已存在则 true，避免重复生成）。
- summary 点到为止；keywords 必须包含字段名、流程编号等可检索关键串。
- 若该原件不含某类，对应数组留空。
{anchor_block}"""


def _step2_system() -> str:
    dir_pipe = _render_dir_list_pipe()
    r = get_registry()
    mandatory = r.mandatory
    mandatory_dir = mandatory.dir if mandatory else "sources"
    mandatory_key = mandatory.key if mandatory else "source"
    anchors = _render_dir_anchors()
    anchor_inline = ""
    if anchors:
        # 取锚点行作为 FILE block 行尾强化
        anchor_inline = "（" + "；".join(
            f"{s.key} 目录是 {s.dir}，不是 {_simple_plural(s.key)}"
            for s in r.types if _is_irregular_dir(s)
        ) + "）"
    return f"""你是企业知识库的 wiki 页生成器。根据 step1 分析 + 源文本，生成 wiki 页。

输出严格使用 FILE block 格式，每个页一个 block：
---FILE: wiki/{dir_pipe}/{{slug}}.md---{anchor_inline}
<frontmatter + body>
---END FILE---

其中 <frontmatter + body> 必须是：首行 `---` 开头的 YAML frontmatter 块、空行、再接正文 body。**绝对不要省略首行 `---`**。完整示例（照此结构）：

---FILE: wiki/{mandatory_dir}/example.md---
---
type: {mandatory_key}
title: "示例原件标题"
created: 2026-08-04
updated: 2026-08-04
tags: [字段A, 字段B]
related: [entity_xxx, concept_yyy]
sources: [docs/example.md]
---

# 示例原件标题

## 关键字段

| 字段 | 值 |
| --- | --- |
| 字段A | ... |
---END FILE---

frontmatter 必须含字段（YAML，数组用内联 [a, b]）：
type / title / created / updated / tags / related / sources
（即首行 `---`，字段逐行，闭合 `---`，空行，正文。frontmatter 第一行永远是 `---`。）

规则：
- 必产 1 张 {mandatory_key} 摘要页：路径 wiki/{mandatory_dir}/{{slug}}.md，title 为原件标题，body 含关键字段表/摘要。
- 可选若干非必产类型页（step1 识别出且 exists=false 的才生成）。
- 禁止生成 index.md / log.md / overview.md（由应用确定性维护）。
- sources 必须含当前原件的 source_identity。
- related 用裸 slug（不带 wiki/ .md [[]]）。
- step1 分析是 context only, do not repeat——不要把分析 JSON 原样写进 body。
- title 含中文时用双引号包裹。
{anchors + chr(10) if anchors else ""}"""


def build_step1_messages(source_identity: str, md_text: str, index_md: str) -> tuple[str, str]:
    user = (
        f"当前 Wiki Index（用于判断实体是否已存在）：\n\n{index_md}\n\n"
        f"原件 source_identity: {source_identity}\n\n"
        f"原件 markdown：\n\n{md_text}\n\n"
        f"请输出分析 JSON。"
    )
    return _step1_system(), user


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
    return _step2_system(), user

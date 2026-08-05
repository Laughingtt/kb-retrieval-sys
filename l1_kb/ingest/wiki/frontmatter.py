"""frontmatter 解析/序列化/合并 —— M2 设计 §2.2、§3.6。

吸收 llm_wiki frontmatter 统一字段（type/title/created/updated/tags/related/sources）
与 UNION_FIELDS/LOCKED_FIELDS 合并语义。YAML 内联数组，确定性可往返。
理解原理后用 Python 重新实现，非复制 llm_wiki 源码。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .page_types import LOCKED_FIELDS, UNION_FIELDS

__all__ = [
    "Frontmatter",
    "parse",
    "dump",
    "union_arrays",
    "stamp_dates",
    "canonicalize_sources",
]


@dataclass
class Frontmatter:
    type: str = ""
    title: str = ""
    created: str = ""
    updated: str = ""
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Frontmatter":
        def _as_list(v):
            if v is None:
                return []
            if isinstance(v, list):
                return [str(x) for x in v]
            return [str(v)]

        def _s(v):
            return "" if v is None else str(v)

        return cls(
            type=_s(d.get("type", "")),
            title=_s(d.get("title", "")),
            created=_s(d.get("created", "")),
            updated=_s(d.get("updated", "")),
            tags=_as_list(d.get("tags")),
            related=_as_list(d.get("related")),
            sources=_as_list(d.get("sources")),
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "tags": list(self.tags),
            "related": list(self.related),
            "sources": list(self.sources),
        }


def _inline_array(items: list[str]) -> str:
    """YAML 内联数组：[a, b, c]。项内含特殊字符则加引号。"""
    parts = []
    for it in items:
        if any(c in it for c in ":#[]{},&*!|>'\"%@`") or it != it.strip():
            parts.append(json_quote(it))
        else:
            parts.append(it)
    return "[" + ", ".join(parts) + "]"


def json_quote(s: str) -> str:
    import json

    return json.dumps(s, ensure_ascii=False)


def _looks_like_yaml_kv_lines(text: str) -> bool:
    """text 是否像裸 frontmatter（多行 `key: value`），用于兜底识别 LLM 漏写首行 --- 的情况。"""
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return False
    kv = 0
    for ln in lines:
        s = ln.strip()
        # 跳过数组续行/纯数组行
        if s.startswith("- ") or s.startswith("["):
            continue
        if ":" in s:
            kv += 1
    return kv >= 2  # 至少 2 个 key:value 才认定为 frontmatter


def parse(content: str) -> tuple[Frontmatter, str]:
    """解析 wiki 页文本：首尾 --- 包裹的 YAML frontmatter + body。

    无 frontmatter → 返回空 Frontmatter + 原文。
    兜底：若 LLM 漏写首行 `---`（content 以 `key: value` 开头、随后有独立 `---` 闭合），
    仍按裸 frontmatter 解析，避免写出双层 frontmatter 的坏页。
    """
    if not content.startswith("---"):
        # 裸 frontmatter 兜底：找首个独立 `---` 行作为闭合
        # 仅当前段像 key:value YAML 时才认定，避免把纯正文误判。
        end = content.find("\n---")
        if end != -1:
            head = content[:end]
            if _looks_like_yaml_kv_lines(head):
                yaml_text = head
                body = content[end + 4 :]  # 跳过 \n---
                while body.startswith("\r\n") or body.startswith("\n"):
                    body = body[1:] if body.startswith("\n") else body[2:]
                try:
                    d = yaml.safe_load(yaml_text) or {}
                except yaml.YAMLError:
                    d = {}
                return Frontmatter.from_dict(d), body
        return Frontmatter(), content
    # 标准：首尾 --- 包裹
    rest = content[3:]
    # 跳过首个换行
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end == -1:
        return Frontmatter(), content
    yaml_text = rest[:end]
    body = rest[end + 4 :]  # 跳过 \n---
    # 剥离 body 前导换行（frontmatter 与正文间的空行）
    while body.startswith("\r\n") or body.startswith("\n"):
        body = body[1:] if body.startswith("\n") else body[2:]
    try:
        d = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        d = {}
    return Frontmatter.from_dict(d), body


def dump(meta: Frontmatter) -> str:
    """序列化为 YAML frontmatter 文本（含首尾 ---）。内联数组格式。"""
    lines = ["---"]
    lines.append(f"type: {meta.type}")
    lines.append(f"title: {json_quote(meta.title)}")
    lines.append(f"created: {meta.created}")
    lines.append(f"updated: {meta.updated}")
    lines.append(f"tags: {_inline_array(meta.tags)}")
    lines.append(f"related: {_inline_array(meta.related)}")
    lines.append(f"sources: {_inline_array(meta.sources)}")
    lines.append("---")
    return "\n".join(lines)


def union_arrays(existing: Frontmatter, new: Frontmatter) -> Frontmatter:
    """合并：UNION_FIELDS 并集（保序去重），LOCKED_FIELDS 回填 existing 旧值。updated 取新。"""
    merged = Frontmatter(
        type=existing.type,          # locked
        title=existing.title,        # locked
        created=existing.created,    # locked
        updated=new.updated,
    )
    for f in UNION_FIELDS:
        seq = []
        for v in getattr(existing, f) + getattr(new, f):
            if v not in seq:
                seq.append(v)
        setattr(merged, f, seq)
    return merged


def stamp_dates(meta: Frontmatter, today: str, *, is_new: bool) -> Frontmatter:
    """强制日期：新页 created=updated=today；已有页 created 不变、updated=today。"""
    out = Frontmatter(
        type=meta.type, title=meta.title,
        created=meta.created if not is_new else today,
        updated=today,
        tags=list(meta.tags), related=list(meta.related), sources=list(meta.sources),
    )
    if is_new and not out.created:
        out.created = today
    return out


def canonicalize_sources(meta: Frontmatter, source_identity: str) -> Frontmatter:
    """强制 sources 含当前 source_identity，剔除非法引用（对路径/../index/log/.cache）。"""
    out = Frontmatter(
        type=meta.type, title=meta.title, created=meta.created, updated=meta.updated,
        tags=list(meta.tags), related=list(meta.related), sources=list(meta.sources),
    )
    # 注入当前源
    if source_identity not in out.sources:
        out.sources.insert(0, source_identity)
    # 过滤非法
    BAD = ("..", "/index", "/log", ".cache/", ".llm-wiki/")
    out.sources = [
        s for s in out.sources
        if not s.startswith("/") and not any(b in s for b in BAD)
    ]
    # 去重保序
    seen, dedup = set(), []
    for s in out.sources:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    out.sources = dedup
    return out

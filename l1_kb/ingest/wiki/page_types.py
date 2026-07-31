"""4 类 wiki 页 + dir↔type 映射 + frontmatter schema 常量 —— M2 设计 §2。

吸收 llm_wiki GENERATION_WIKI_TYPES（9 类）裁剪为 4 类，适配企业知识库。
process 为本设计新增（llm_wiki 无），承载企业流程/制度文档。
dir↔type 双向校验吸收 llm_wiki validateWikiPageRouting 原理（Python 重实现）。
"""

from __future__ import annotations

import re

__all__ = [
    "PAGE_TYPES",
    "TYPE_TO_DIR",
    "DIR_TO_TYPE",
    "LOCKED_FIELDS",
    "UNION_FIELDS",
    "dir_for_type",
    "type_for_dir",
    "is_valid_type",
    "validate_routing",
    "sanitize_slug",
    "slug_from_source_identity",
]

# P0 四类页（吸收 llm_wiki 9 类裁剪）
PAGE_TYPES = frozenset({"source", "entity", "concept", "process"})

# type → 目录段（吸收 llm_wiki dir↔type 映射）
TYPE_TO_DIR = {
    "source": "sources",
    "entity": "entities",
    "concept": "concepts",
    "process": "process",
}
DIR_TO_TYPE = {v: k for k, v in TYPE_TO_DIR.items()}

# frontmatter 字段分类（吸收 llm_wiki LOCKED_FIELDS / UNION_FIELDS）
LOCKED_FIELDS = ("type", "title", "created")
UNION_FIELDS = ("sources", "tags", "related")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def dir_for_type(page_type: str) -> str:
    return TYPE_TO_DIR[page_type]


def type_for_dir(dir_name: str) -> str | None:
    return DIR_TO_TYPE.get(dir_name)


def is_valid_type(page_type: str) -> bool:
    return page_type in PAGE_TYPES


def validate_routing(path: str, page_type: str) -> bool:
    """path 与 page_type 所在目录是否一致（吸收 llm_wiki validateWikiPageRouting）。

    path 形如 wiki/sources/{slug}.md；要求 wiki/ 前缀且第二段 == 该 type 对应目录。
    """
    if not page_type in PAGE_TYPES:
        return False
    parts = path.replace("\\", "/").split("/")
    if len(parts) < 2 or parts[0] != "wiki":
        return False
    return parts[1] == TYPE_TO_DIR[page_type]


def sanitize_slug(raw: str) -> str:
    """slug 规范化：仅 [a-z0-9_]，非合规字符 → _，压缩/去首尾下划线，空兜底返回空串。"""
    s = _SLUG_RE.sub("_", raw.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def slug_from_source_identity(identity: str) -> str:
    """source_identity（相对 raw 路径）→ source 摘要页 slug。

    data_table/order_detail.xlsx → "data_table_order_detail"
    规则同 M1 slugify_path：去扩展名 + 路径段下划线连 + sanitize。
    """
    # 去扩展名
    stem = re.sub(r"\.[^.\\/]+$", "", identity)
    # 路径分隔符 → 下划线
    joined = re.sub(r"[\\/]+", "_", stem)
    return sanitize_slug(joined) or "source"

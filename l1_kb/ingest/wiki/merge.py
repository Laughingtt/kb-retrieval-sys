"""已有 wiki 页合并 —— M2 设计 §3.6。

吸收 llm_wiki writeFileBlocks + mergePageContent 原理，简化合并策略：
- 单源页（existing.sources == [当前源]）→ 替换 body（吸收 replaceExistingBody）
- 多源页 → 追加段落（砍 LLM body 合并/70% 缩水/page-history 备份）
- frontmatter：UNION_FIELDS 并集 + LOCKED_FIELDS 回填旧值
- new_body 完全被 existing 包含 → 不重复追加（去重，§9 待决议采纳）
"""

from __future__ import annotations

import sys

from .frontmatter import (
    Frontmatter,
    canonicalize_sources,
    dump,
    parse,
    stamp_dates,
    union_arrays,
)
from .page_types import validate_routing

__all__ = ["merge_page"]


def _warn(msg: str) -> None:
    print(f"[warn] merge: {msg}", file=sys.stderr)


def merge_page(
    existing_text: str | None,
    new_path: str,
    new_content: str,
    source_identity: str,
    today: str,
    *,
    exists: bool,
) -> str | None:
    """合并/写入一页。返回整页文本；routing 不一致返回 None。"""
    new_fm, new_body = parse(new_content)
    if not validate_routing(new_path, new_fm.type):
        _warn(f"routing 不一致，丢弃: {new_path} type={new_fm.type}")
        return None

    new_fm = canonicalize_sources(new_fm, source_identity)

    if not exists or existing_text is None:
        new_fm = stamp_dates(new_fm, today, is_new=True)
        return dump(new_fm) + "\n\n" + new_body.strip() + "\n"

    existing_fm, existing_body = parse(existing_text)
    existing_fm = canonicalize_sources(existing_fm, source_identity)

    # 单源页 → 替换 body
    is_single_source = existing_fm.sources == [source_identity]
    if is_single_source:
        merged_body = new_body.strip()
    else:
        # 多源页 → 追加段落（去重：new_body 完全被 existing 包含则不追加）
        nb = new_body.strip()
        if nb and nb in existing_body.strip():
            merged_body = existing_body.strip()
        else:
            merged_body = (
                existing_body.strip()
                + f"\n\n## 来源补充: {source_identity}\n\n"
                + nb
            )

    merged_fm = union_arrays(existing_fm, new_fm)
    merged_fm = stamp_dates(merged_fm, today, is_new=False)
    return dump(merged_fm) + "\n\n" + merged_body + "\n"

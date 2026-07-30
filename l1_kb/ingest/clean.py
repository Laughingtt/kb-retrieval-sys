"""清洗编排 —— PRD §6 / §7.1。

单文件清洗流水线（M1）：
    raw_path → is_safe_path 校验 → doc_id 派生 → cleaner.to_markdown
            → SectionSplitter.split → 写 md/{category}/{doc_id}.md

**临时 category**：M1 无 LLM，category 由 raw 子目录第一段派生
（`raw/data_table/order_detail.xlsx` → `data_table`）。
M2 LLM 第1步重分类后，可按 category 字段迁移 md 路径——
因 doc_id 不含 category（F1 稳定），迁移不破坏 doc_id 与引用。TODO(M2)

M1 只写 md/，不写 index.json（M2）、不建向量（M2）。
"""

from __future__ import annotations

from pathlib import Path

from .section_splitter import Section, split
from .cleaners.dispatcher import cleaner_for
from .cleaners.base import CleanerError, PandocNotAvailableError
from .doc_id import make_doc_id
from .safe_path import is_safe_path

__all__ = ["clean_one", "CleanResult"]


class CleanResult:
    """单文件清洗结果。"""

    def __init__(
        self,
        doc_id: str,
        category: str,
        md_path: Path | None,
        sections: list[Section],
        skipped: bool = False,
        reason: str = "",
    ):
        self.doc_id = doc_id
        self.category = category
        self.md_path = md_path
        self.sections = sections
        self.skipped = skipped
        self.reason = reason

    def __repr__(self) -> str:
        if self.skipped:
            return f"CleanResult(skipped, reason={self.reason!r})"
        return (
            f"CleanResult(doc_id={self.doc_id!r}, category={self.category!r}, "
            f"sections={len(self.sections)}, md={self.md_path})"
        )


def _derive_category(raw_root: Path, raw_path: Path) -> str:
    """临时 category：raw 相对路径第一段。TODO(M2) 由 LLM 重分类。

    raw/data_table/order_detail.xlsx → "data_table"
    raw 直接下的文件（无子目录）→ "uncategorized"。
    """
    try:
        rel = raw_path.relative_to(raw_root)
    except ValueError:
        return "uncategorized"
    parts = rel.parts
    if len(parts) > 1:
        return parts[0]
    return "uncategorized"


def clean_one(
    raw_root: Path,
    raw_path: Path,
    md_root: Path,
    *,
    dry_run: bool = False,
) -> CleanResult:
    """清洗单文件：raw_path → md/{category}/{doc_id}.md + sections。

    - is_safe_path 不通过 → 返回 skipped 结果（不抛）。
    - PandocNotAvailableError → 返回 skipped 结果（编排层 warn）。
    - 其他 CleanerError → 向上抛（调用方决定中止/记录）。
    """
    # 1. 路径安全校验
    if not is_safe_path(raw_root, raw_path):
        return CleanResult(
            doc_id="",
            category="",
            md_path=None,
            sections=[],
            skipped=True,
            reason=f"路径不安全/越界: {raw_path}",
        )

    # 2. doc_id 派生（F1 稳定）
    doc_id = make_doc_id(raw_root, raw_path)

    # 3. 临时 category（TODO M2 LLM 重分类）
    category = _derive_category(raw_root, raw_path)

    # 4. 分发 cleaner 并清洗
    cleaner = cleaner_for(raw_path)
    try:
        md_text = cleaner.to_markdown(raw_path)
    except PandocNotAvailableError as e:
        return CleanResult(
            doc_id=doc_id,
            category=category,
            md_path=None,
            sections=[],
            skipped=True,
            reason=str(e),
        )

    # 5. section 切分（§6.3）
    sections = split(md_text)

    # 6. 写 md/{category}/{doc_id}.md
    md_path = md_root / category / f"{doc_id}.md"
    if not dry_run:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")

    return CleanResult(
        doc_id=doc_id,
        category=category,
        md_path=md_path if not dry_run else None,
        sections=sections,
    )

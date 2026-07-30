"""Cleaner 分发 —— 按文件扩展名选 Cleaner。

PRD §6.2：四类原件 PDF/Word/Excel/MD 各有 Cleaner。
未知扩展名 raise CleanerError（编排层 warn 跳过）。
"""

from __future__ import annotations

from pathlib import Path

from .base import BaseCleaner, CleanerError
from .excel_cleaner import ExcelCleaner
from .markdown_cleaner import MarkdownCleaner
from .pdf_cleaner import PdfCleaner
from .word_cleaner import WordCleaner

__all__ = ["get_cleaner", "SUPPORTED_EXTS"]

_CLEANERS: dict[str, type[BaseCleaner]] = {
    ".pdf": PdfCleaner,
    ".docx": WordCleaner,
    ".xlsx": ExcelCleaner,
    ".md": MarkdownCleaner,
}

SUPPORTED_EXTS = tuple(_CLEANERS.keys())


def get_cleaner(ext: str) -> BaseCleaner:
    """按扩展名返回 Cleaner 实例。未知扩展名 raise CleanerError。"""
    key = ext.lower()
    if key not in _CLEANERS:
        raise CleanerError(f"不支持的文件类型: {ext}")
    return _CLEANERS[key]()


def cleaner_for(path: Path) -> BaseCleaner:
    """按 Path 后缀返回 Cleaner。"""
    return get_cleaner(path.suffix)

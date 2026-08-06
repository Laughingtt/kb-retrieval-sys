"""四类 Cleaner 单测 —— PRD §6.2.

验证点（plan 验证项 #1, #2, #8）：
- 各 cleaner 输出含 pipe 表（`|`）与 ATX 标题。
- Excel 宽表 F4：>20 列 → 拆 `## {sheet名} — {组名}` 子 section。
- §6.4 示例对齐：order_detail.xlsx 清洗后结构。
- pandoc 未装 → WordCleaner raise PandocNotAvailableError。
- MarkdownCleaner：Setext → ATX 规范化。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kb_retrieval.kb.ingest.cleaners.base import PandocNotAvailableError
from kb_retrieval.kb.ingest.cleaners.excel_cleaner import ExcelCleaner
from kb_retrieval.kb.ingest.cleaners.markdown_cleaner import MarkdownCleaner
from kb_retrieval.kb.ingest.cleaners.pdf_cleaner import PdfCleaner
from kb_retrieval.kb.ingest.cleaners.word_cleaner import WordCleaner


def _has_pipe_table(md: str) -> bool:
    return any(line.lstrip().startswith("|") for line in md.splitlines())


def _has_atx_heading(md: str) -> bool:
    import re
    return any(re.match(r"^#{1,3}\s+\S", line) for line in md.splitlines())


class TestMarkdownCleaner:
    def test_passthrough_atx(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("# Title\n\nbody\n", encoding="utf-8")
        md = MarkdownCleaner().to_markdown(f)
        assert "# Title" in md
        assert md.endswith("\n")

    def test_setext_to_atx(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("Title\n=====\n\nSub\n-----\n\ntext\n", encoding="utf-8")
        md = MarkdownCleaner().to_markdown(f)
        assert "# Title" in md
        assert "## Sub" in md
        # 原 setext 下划线行被消除
        assert "=====" not in md
        assert "-----" not in md

    def test_pipe_table_preserved(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
        md = MarkdownCleaner().to_markdown(f)
        assert _has_pipe_table(md)


class TestExcelCleaner:
    def test_two_sheets_two_sections(self, order_xlsx: Path):
        md = ExcelCleaner().to_markdown(order_xlsx)
        assert md.count("## ") == 2  # 订单 / 订单明细
        assert "订单" in md
        assert "订单明细" in md
        assert _has_pipe_table(md)
        assert "order_id" in md
        assert "O1001" in md

    def test_section_ids_from_split(self, order_xlsx: Path):
        from kb_retrieval.kb.ingest.section_splitter import split

        md = ExcelCleaner().to_markdown(order_xlsx)
        sections = split(md)
        assert len(sections) == 2
        assert [s.section_id for s in sections] == ["s0", "s1"]
        # 两张表 section 都应标记 is_table
        assert all(s.is_table for s in sections)

    def test_wide_table_grouped(self, wide_xlsx: Path):
        """F4：>20 列 → 按前缀拆 `## {sheet} — {组名}` 子 section。"""
        md = ExcelCleaner().to_markdown(wide_xlsx)
        # 应出现多个带「 — 」的子 section 标题
        assert md.count("## ") >= 2
        assert " — " in md or " — " in md  # 分组子标题

    def test_wide_table_all_columns_covered(self, wide_xlsx: Path):
        wide_xlsx_copy = wide_xlsx
        md = ExcelCleaner().to_markdown(wide_xlsx_copy)
        # 关键列名仍应在输出中
        assert "order_id" in md
        assert "amount_total" in md
        assert "time_create" in md


class TestPdfCleaner:
    def test_pdf_has_heading_and_table(self, sample_pdf: Path):
        md = PdfCleaner().to_markdown(sample_pdf)
        # PyMuPDF4LLM 应产出标题与表格
        assert _has_atx_heading(md) or "Field" in md
        # 表格信息应在（pipe 表 或 兜底补充）
        assert "order_id" in md or "field" in md.lower()


class TestWordCleaner:
    def test_pandoc_missing_raises(self, tmp_path: Path, monkeypatch):
        """pandoc 未装 → PandocNotAvailableError（优雅跳过信号）。"""
        f = tmp_path / "a.docx"
        f.write_bytes(b"fake docx")  # 内容不重要，因前置 which 检测先失败
        monkeypatch.setattr(shutil, "which", lambda x: None)
        with pytest.raises(PandocNotAvailableError):
            WordCleaner().to_markdown(f)


class TestDispatcher:
    def test_dispatch_by_ext(self):
        from kb_retrieval.kb.ingest.cleaners.dispatcher import get_cleaner

        assert isinstance(get_cleaner(".md"), MarkdownCleaner)
        assert isinstance(get_cleaner(".xlsx"), ExcelCleaner)
        assert isinstance(get_cleaner(".pdf"), PdfCleaner)
        assert isinstance(get_cleaner(".docx"), WordCleaner)

    def test_unknown_ext_raises(self):
        from kb_retrieval.kb.ingest.cleaners.base import CleanerError
        from kb_retrieval.kb.ingest.cleaners.dispatcher import get_cleaner

        with pytest.raises(CleanerError):
            get_cleaner(".txt")

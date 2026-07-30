"""端到端编排测试 —— PRD §6.3 / §7.1 / plan 验证项 #5/#6/#7/#8。

clean_one 全流程：is_safe_path → doc_id → cleaner → split → 写 md/。
验证：
- order_detail.xlsx → md 写入 md/{category}/{doc_id}.md，doc_id 格式正确。
- dry-run 不写文件。
- 路径越界 → skipped。
- pandoc 缺失 → .docx skipped，不中断。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from l1_kb.ingest.clean import clean_one


def test_clean_one_excel_writes_md(tmp_path: Path, order_xlsx: Path):
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    # 把 fixture 复制进 raw/data_table/
    target_dir = raw_root / "data_table"
    target_dir.mkdir()
    target = target_dir / "order_detail.xlsx"
    shutil.copy(order_xlsx, target)

    md_root = tmp_path / "md"
    result = clean_one(raw_root, target, md_root)

    assert not result.skipped
    # doc_id 格式：slug__sha256[:8]
    assert re.match(r"^data_table_order_detail__[0-9a-f]{8}$", result.doc_id)
    assert result.category == "data_table"
    assert len(result.sections) == 2  # 两个 sheet
    # md 文件确实写入
    assert result.md_path is not None
    assert result.md_path.exists()
    assert result.md_path.name == f"{result.doc_id}.md"
    assert result.md_path.parent.name == "data_table"


def test_clean_one_dry_run_no_write(tmp_path: Path, order_xlsx: Path):
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    target_dir = raw_root / "data_table"
    target_dir.mkdir()
    target = target_dir / "order_detail.xlsx"
    shutil.copy(order_xlsx, target)

    md_root = tmp_path / "md"
    result = clean_one(raw_root, target, md_root, dry_run=True)
    assert not result.skipped
    assert result.md_path is None
    assert not md_root.exists() or not any(md_root.rglob("*.md"))


def test_clean_one_unsafe_path_skipped(tmp_path: Path):
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# x\n", encoding="utf-8")
    md_root = tmp_path / "md"
    result = clean_one(raw_root, outside, md_root)
    assert result.skipped
    assert "不安全" in result.reason or "越界" in result.reason


def test_clean_one_markdown(tmp_path: Path):
    raw_root = tmp_path / "raw" / "data_product"
    raw_root.mkdir(parents=True)
    f = raw_root / "api_doc.md"
    f.write_text("# API\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    raw_base = tmp_path / "raw"
    md_root = tmp_path / "md"
    result = clean_one(raw_base, f, md_root)
    assert not result.skipped
    assert result.category == "data_product"
    assert result.md_path.exists()
    assert result.sections[0].title == "API"


def test_clean_one_docx_pandoc_missing_skipped(tmp_path: Path, monkeypatch):
    """pandoc 缺失 → .docx skipped，不抛异常（优雅跳过）。"""
    raw_root = tmp_path / "raw" / "process"
    raw_root.mkdir(parents=True)
    f = raw_root / "process.docx"
    f.write_bytes(b"fake")
    raw_base = tmp_path / "raw"
    md_root = tmp_path / "md"
    monkeypatch.setattr(shutil, "which", lambda x: None)
    result = clean_one(raw_base, f, md_root)
    assert result.skipped
    assert "pandoc" in result.reason.lower()

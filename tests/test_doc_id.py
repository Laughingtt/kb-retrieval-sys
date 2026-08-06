"""doc_id 单测 —— PRD §7.1.1, F1。

验证点（plan 验证项 #5）：
- 格式 = slug(raw相对路径) + "__" + sha256[:8]
- 不含 category（稳定性核心）
- 同路径不同内容 → digest 变 → doc_id 变
- slugify 规则（去扩展名、/ → _、非字母数字 → _、小写、首尾去 _、空串兜底 doc）
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kb_retrieval.kb.ingest.doc_id import make_doc_id, slugify_path


class TestSlugifyPath:
    def test_basic_with_extension(self):
        assert slugify_path(Path("data_table/order_detail.xlsx")) == "data_table_order_detail"

    def test_strips_extension(self):
        assert slugify_path(Path("intro.pdf")) == "intro"

    def test_directory_separator_becomes_underscore(self):
        assert slugify_path(Path("a/b/c.md")) == "a_b_c"

    def test_non_ascii_replaced(self):
        # 全非 ASCII 字母数字（中文路径）→ 下划线压缩后首尾去除 → 空 → 兜底 doc
        # 与中文混合的字母会保留：a产品b.md → a_b
        assert slugify_path(Path("a产品b.md")) == "a_b"
        assert slugify_path(Path("产品/说明.md")) == "doc"

    def test_mixed_ascii_non_ascii(self):
        assert slugify_path(Path("data_table/订单.md")) == "data_table"

    def test_leading_trailing_underscore_stripped(self):
        assert slugify_path(Path("产品说明.md")) == "doc"  # 全非字母数字 → 空 → 兜底 doc

    def test_lowercase(self):
        assert slugify_path(Path("DataProduct/Foo.md")) == "dataproduct_foo"

    def test_collapsed_separators(self):
        # 连续非字母数字字符压缩为单个 _
        assert slugify_path(Path("a--b!!c.md")) == "a_b_c"

    def test_empty_fallback_to_doc(self):
        assert slugify_path(Path("产品.md")) == "doc"


class TestMakeDocId:
    def test_format(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        f = raw_root / "data_table" / "order_detail.xlsx"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"hello")
        digest = hashlib.sha256(b"hello").hexdigest()[:8]
        doc_id = make_doc_id(raw_root, f)
        assert doc_id == f"data_table_order_detail__{digest}"

    def test_no_category_in_doc_id(self, tmp_path: Path):
        """F1 核心：category 不进 doc_id。即便文件在 raw/data_table/ 下，
        doc_id 的 slug 来自路径，但不依赖任何 category 字段。"""
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        f = raw_root / "data_table" / "x.md"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"content")
        doc_id = make_doc_id(raw_root, f)
        # doc_id 形如 data_table_x__xxxxxxxx —— slug 来自相对路径，无独立 category 注入
        assert doc_id.startswith("data_table_x__")
        assert len(doc_id.split("__")[1]) == 8

    def test_same_path_different_content_changes_doc_id(self, tmp_path: Path):
        """同路径内容变 → sha256 变 → doc_id 变（增量覆盖判定依据）。"""
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        f = raw_root / "a.md"
        f.write_bytes(b"v1")
        id1 = make_doc_id(raw_root, f)
        f.write_bytes(b"v2")
        id2 = make_doc_id(raw_root, f)
        assert id1 != id2
        # slug 部分相同，仅 digest 不同
        assert id1.split("__")[0] == id2.split("__")[0] == "a"

    def test_different_path_same_content_different_doc_id(self, tmp_path: Path):
        """不同路径同内容 → slug 不同 → doc_id 不同。"""
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        (raw_root / "a").mkdir()
        (raw_root / "b").mkdir()
        f1 = raw_root / "a" / "x.md"
        f2 = raw_root / "b" / "x.md"
        f1.write_bytes(b"same")
        f2.write_bytes(b"same")
        assert make_doc_id(raw_root, f1) != make_doc_id(raw_root, f2)

    def test_digest_is_sha256_first8(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        f = raw_root / "doc.md"
        payload = b"some bytes for hashing"
        f.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()[:8]
        assert make_doc_id(raw_root, f).endswith(f"__{expected}")

    def test_path_outside_root_raises(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        outside = tmp_path / "elsewhere.md"
        outside.write_bytes(b"x")
        with pytest.raises(ValueError):
            make_doc_id(raw_root, outside)  # relative_to 抛 ValueError，符合预期

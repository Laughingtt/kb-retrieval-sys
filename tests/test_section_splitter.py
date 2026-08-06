"""SectionSplitter 单测 —— PRD §6.3（检索质量命脉）。

验证点（plan 验证项 #3, #4）：
- 按 #/##/### 切 section，section_id s0/s1/...
- line_start=标题行(1-based)，line_end=下一标题-1（末尾到 EOF）
- 无标题 → 单 s0
- 过长(>200)非表 → 按空行二次切分；表 section 豁免
- 表 section is_table=True
"""

from __future__ import annotations

from kb_retrieval.kb.ingest.section_splitter import Section, split


def _md(text: str) -> str:
    return text.strip() + "\n"


class TestBasicSplit:
    def test_single_heading(self):
        md = _md("# Title\n\nbody line\n")
        sections = split(md)
        assert len(sections) == 1
        s = sections[0]
        assert s.section_id == "s0"
        assert s.title == "Title"
        assert s.level == 1
        assert s.line_start == 1
        assert s.line_end == 3  # 3 lines total

    def test_multiple_headings_sequential(self):
        md = _md("# A\n\na-body\n\n## B\n\nb-body\n")
        # splitlines() drops the trailing newline → 7 lines:
        # 1 #A, 2 (blank), 3 a-body, 4 (blank), 5 ##B, 6 (blank), 7 b-body
        sections = split(md)
        assert len(sections) == 2
        assert [s.section_id for s in sections] == ["s0", "s1"]
        assert [s.title for s in sections] == ["A", "B"]
        assert [s.level for s in sections] == [1, 2]
        # s0: title line 1 → ends at next heading line - 1 = 5-1 = 4
        assert sections[0].line_start == 1
        assert sections[0].line_end == 4
        # s1: title line 5 → ends at last content line 7
        assert sections[1].line_start == 5
        assert sections[1].line_end == 7

    def test_three_levels(self):
        md = _md("# A\n## B\n### C\nbody\n")
        sections = split(md)
        assert len(sections) == 3
        assert [s.level for s in sections] == [1, 2, 3]
        assert [s.title for s in sections] == ["A", "B", "C"]

    def test_heading_levels_do_not_nest_sections(self):
        """#/##/### 都是同级 section 边界（不嵌套），逐个标题行切。"""
        md = _md("## A\n## B\n")
        sections = split(md)
        assert len(sections) == 2

    def test_section_ids_stable_order(self):
        md = _md("# A\n# B\n# C\n")
        sections = split(md)
        assert [s.section_id for s in sections] == ["s0", "s1", "s2"]


class TestNoHeading:
    def test_no_heading_single_section(self):
        md = _md("just some text\nno heading here\n")
        sections = split(md)
        assert len(sections) == 1
        s = sections[0]
        assert s.section_id == "s0"
        assert s.title == ""
        assert s.level == 0
        assert s.line_start == 1
        assert s.line_end == 2

    def test_empty_text(self):
        sections = split("")
        assert len(sections) == 1
        assert sections[0].section_id == "s0"
        assert sections[0].line_end >= 1


class TestTableSectionExemption:
    def _pipe_table_md(self) -> str:
        return _md(
            "## Sheet 订单\n\n"
            "| 列1 | 列2 | 列3 |\n"
            "|---|---|---|\n"
            "| a | b | c |\n"
            "| d | e | f |\n"
        )

    def test_table_section_marked_is_table(self):
        sections = split(self._pipe_table_md())
        assert len(sections) == 1
        assert sections[0].is_table is True

    def test_table_section_exempt_from_oversize_split(self):
        """超过 200 行的表 section 不被二次切分。"""
        header = "## BigTable\n\n| col |\n|---|\n"
        rows = "\n".join(f"| r{i} |" for i in range(250))
        md = header + rows + "\n"
        sections = split(md, max_lines=50)
        assert len(sections) == 1  # 表豁免，不被切
        assert sections[0].is_table is True

    def test_non_table_oversize_split(self):
        """超过阈值的非表 section 按空行二次切分。"""
        para1 = "\n".join(f"line {i}" for i in range(40))
        para2 = "\n".join(f"row {i}" for i in range(40))
        md = _md(f"# Long\n\n{para1}\n\n{para2}\n")
        sections = split(md, max_lines=50)
        assert len(sections) >= 2
        # 第一个保留原标题，后续是「续 N」
        assert sections[0].title == "Long"
        assert sections[1].title.startswith("Long（续")
        # 行号落在原文范围内、连续
        assert sections[0].line_start == 1
        assert sections[1].line_start <= sections[0].line_end + 2

    def test_normal_text_section_not_marked_table(self):
        md = _md("# Plain\n\nsome prose here\n")
        sections = split(md)
        assert sections[0].is_table is False


class TestLineNumbers:
    def test_line_end_is_last_line_for_final_section(self):
        lines = ["# A", "", "body"]
        md = "\n".join(lines) + "\n"
        sections = split(md)
        assert sections[0].line_end == 3

    def test_content_between_two_headings(self):
        md = _md("# A\nx\ny\nz\n# B\nm\n")
        # 1 #A, 2 x, 3 y, 4 z, 5 #B, 6 m
        sections = split(md)
        assert sections[0].line_start == 1
        assert sections[0].line_end == 4
        assert sections[1].line_start == 5
        assert sections[1].line_end == 6

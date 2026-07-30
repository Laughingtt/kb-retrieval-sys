"""section 切分 —— PRD §6.3（检索质量命脉）。

清洗产出的 markdown 按 #/##/### 标题切分。
**section 是最小检索单元 = 索引单元 = 加载单元**（三层一致）。
行号范围由脚本解析标题行号确定（确定性，不靠 LLM）。

切分规则（PRD §6.3）：
1. 逐行扫描，正则 `^#{1,3}\\s+(.+)` 匹配标题行，记录行号与层级。
2. 两个相邻标题行之间为一个 section：
   line_start = 标题行号，line_end = 下一个标题行号 - 1（末尾 section 到文件末）。
3. section 内容 = 标题 + 该段正文（含表格）。
4. 无标题文档兜底：整篇作为一个 section s0。
5. 过长 section（>MAX_LINES，默认 200）且**非表** → 按段落空行二次切分；
   **表格 section 豁免**（表格不可按空行切碎，否则字段说明断行，见 §6.2.3）。

section_id 稳定：按出现顺序 s0/s1/...，重摄入同一文档时顺序一致，
保证向量索引稳定键 `doc_id__section_id` 稳定（行号不外泄，见 §9.2.2）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Section", "split"]

# ATX 标题行：1-3 个 # 后接空格 + 标题文本
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
# pipe 表格行（含分隔行 |---|---|）
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")

MAX_LINES = 200  # 过长 section 二次切分阈值（PRD §6.3 规则5）


@dataclass
class Section:
    """一个 section = 检索单元 = 索引单元 = 加载单元。"""

    section_id: str      # s0, s1, ... 按出现顺序
    title: str           # 标题文本（无 # 前缀）；无标题文档为 ""
    line_start: int      # 标题行号（1-based）；无标题为 1
    line_end: int        # 下一个标题行号 - 1；末尾到文件末
    level: int           # 标题层级 1/2/3；无标题为 0
    is_table: bool       # True 则豁免 200 行二次切分（表 section）


def _is_table_section(lines: list[str], start_idx: int, end_idx: int) -> bool:
    """判断该 section 的正文是否以 pipe 表格开头（首非空行以 | 开头）。

    Excel sheet section 体为整张 pipe 表 → 标记 is_table=True，豁免二次切分。
    """
    for i in range(start_idx, end_idx + 1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        # 跳过标题行本身，看正文首行
        if _HEADING_RE.match(lines[i]):
            continue
        return bool(_TABLE_ROW_RE.match(lines[i]))
    return False


def split(md_text: str, max_lines: int = MAX_LINES) -> list[Section]:
    """把清洗后 markdown 切成 sections。

    返回按出现顺序的 Section 列表，section_id = s0, s1, ...
    行号 1-based；line_start=标题行，line_end=下一标题-1（末尾到 EOF）。
    """
    lines = md_text.splitlines()

    # 1. 扫描所有标题行（0-based 行号 + 层级 + 标题文本）
    headings: list[tuple[int, int, str]] = []  # (line_idx, level, title)
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append((idx, len(m.group(1)), m.group(2).strip()))

    # 3. 无标题文档兜底：整篇一个 s0
    if not headings:
        return [
            Section(
                section_id="s0",
                title="",
                line_start=1,
                line_end=max(len(lines), 1),
                level=0,
                is_table=False,
            )
        ]

    # 2. 相邻标题之间为一个 section
    raw_sections: list[tuple[int, int, int, str]] = []  # (start_idx, end_idx, level, title)
    for i, (idx, level, title) in enumerate(headings):
        start_idx = idx
        end_idx = headings[i + 1][0] - 1 if i + 1 < len(headings) else len(lines) - 1
        raw_sections.append((start_idx, end_idx, level, title))

    # 4. 过长 section 且非表 → 按段落空行二次切分；表 section 豁免
    sections: list[Section] = []
    for start_idx, end_idx, level, title in raw_sections:
        is_table = _is_table_section(lines, start_idx, end_idx)
        span = end_idx - start_idx + 1
        if span > max_lines and not is_table:
            # 按段落空行二次切分
            sub = _split_long_section(lines, start_idx, end_idx, level, title)
            sections.extend(sub)
        else:
            sections.append(
                Section(
                    section_id="",  # 稍后统一编号
                    title=title,
                    line_start=start_idx + 1,
                    line_end=end_idx + 1,
                    level=level,
                    is_table=is_table,
                )
            )

    # 5. section_id 按出现顺序 s0/s1/...（重摄入稳定）
    for i, s in enumerate(sections):
        s.section_id = f"s{i}"
    return sections


def _split_long_section(
    lines: list[str],
    start_idx: int,
    end_idx: int,
    level: int,
    title: str,
) -> list[Section]:
    """对过长非表 section 按段落空行二次切分。

    第一个子段保留原标题；后续子段用 "{title}（续 N）" 作为占位标题，
    line_start/end 仍指向原文行号（确定性，不靠 LLM）。
    """
    # 找段落空行边界（连续空行视为单一边界）
    boundaries: list[int] = [start_idx]
    for i in range(start_idx + 1, end_idx + 1):
        if lines[i].strip() == "" and i - 1 >= start_idx and lines[i - 1].strip() != "":
            boundaries.append(i)
    boundaries.append(end_idx + 1)  # 末尾哨兵（exclusive）

    out: list[Section] = []
    cont = 0
    for b in range(len(boundaries) - 1):
        seg_start = boundaries[b]
        seg_end = boundaries[b + 1] - 1
        # 跳过纯空行段
        if all(lines[j].strip() == "" for j in range(seg_start, seg_end + 1)):
            continue
        seg_title = title if cont == 0 else f"{title}（续 {cont}）"
        out.append(
            Section(
                section_id="",
                title=seg_title,
                line_start=seg_start + 1,
                line_end=seg_end + 1,
                level=level,
                is_table=False,
            )
        )
        cont += 1
    return out

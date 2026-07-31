"""片段切分 —— M2 设计 §5.5。按 section 1-based 行号范围从 wiki 页原文切 snippet。"""

from __future__ import annotations

__all__ = ["make_snippet"]


def make_snippet(md_text: str, line_start: int, line_end: int, max_chars: int = 500) -> str:
    """按 1-based [line_start, line_end] 切片，超长尾部截断。越界安全。"""
    lines = md_text.splitlines()
    if not lines:
        return ""
    start = max(line_start - 1, 0)
    end = line_end if line_end <= len(lines) else len(lines)
    seg = lines[start:end]
    out = "\n".join(seg)
    return out[:max_chars]

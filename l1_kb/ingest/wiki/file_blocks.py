"""解析 ---FILE:...---...---END FILE--- block —— M2 设计 §3.5。

吸收 llm_wiki parseFileBlocks + FILE_BLOCK_REGEX 原理（Python 重实现）。
未闭合 block（截断）→ 丢弃 + warn（不调 LLM 修复，砍 llm_wiki 截断修复路径）。
每个 path 过 is_safe_wiki_path，不通过丢弃 + warn。
"""

from __future__ import annotations

import re
import sys

from .safe_path import is_safe_wiki_path

__all__ = ["parse_file_blocks"]

_BLOCK_RE = re.compile(
    r"---FILE:\s*([^\n]+?)\s*---\n([\s\S]*?)---END FILE---"
)


def _warn(msg: str) -> None:
    print(f"[warn] file_blocks: {msg}", file=sys.stderr)


def parse_file_blocks(text: str) -> list[tuple[str, str]]:
    """从 LLM 输出文本解析 FILE block。

    返回 [(path, content), ...]。未闭合 block 不被正则匹配（自然丢弃）。
    非法 path 经 is_safe_wiki_path 过滤。
    """
    if not text:
        return []
    blocks: list[tuple[str, str]] = []
    for m in _BLOCK_RE.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        if not is_safe_wiki_path(path):
            _warn(f"丢弃非法/不安全 path: {path!r}")
            continue
        blocks.append((path, content))
    # 检测未闭合 block（有 ---FILE: 但无对应 ---END FILE---）→ warn
    opened = re.findall(r"---FILE:\s*([^\n]+?)\s*---", text)
    closed = [b[0] for b in blocks]
    for p in opened:
        if p.strip() not in closed and not is_safe_wiki_path(p.strip()):
            continue  # 已因不安全路径 warn 过
        # 仅对安全 path 但未闭合的发 warn
        if is_safe_wiki_path(p.strip()) and p.strip() not in closed:
            _warn(f"丢弃未闭合 block: {p.strip()!r}")
    return blocks

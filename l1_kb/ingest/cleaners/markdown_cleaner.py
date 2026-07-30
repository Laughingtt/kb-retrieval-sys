"""Markdown 清洗 —— PRD §6.2.4。

原件即 markdown，做最小规范化：
- Setext 标题（下划线式 `=====`/`-----`）→ ATX（`#`/`##`）。
- 去除尾部空白、统一换行。
- 其余原样保留（pipe 表、列表、代码块不动）。

不调 LLM，纯确定性。
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import BaseCleaner

__all__ = ["MarkdownCleaner"]

# Setext 标题：一行文本 + 下一行全 = 或全 -
_SETEXT_H1_RE = re.compile(r"^(=+)\s*$")
_SETEXT_H2_RE = re.compile(r"^(-+)\s*$")


class MarkdownCleaner(BaseCleaner):
    def to_markdown(self, raw_path: Path) -> str:
        text = raw_path.read_text(encoding="utf-8")
        return self.normalize(text)

    @staticmethod
    def normalize(text: str) -> str:
        lines = text.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # 检测下一行是否为 setext 下划线
            if i + 1 < len(lines) and line.strip():
                nxt = lines[i + 1]
                if _SETEXT_H1_RE.match(nxt):
                    out.append(f"# {line.strip()}")
                    i += 2
                    continue
                if _SETEXT_H2_RE.match(nxt):
                    out.append(f"## {line.strip()}")
                    i += 2
                    continue
            out.append(line.rstrip())
            i += 1
        # 去除尾部空行，统一末尾换行
        result = "\n".join(out).rstrip() + "\n"
        return result

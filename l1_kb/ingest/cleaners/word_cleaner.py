"""Word（.docx）清洗 —— PRD §6.2.2。

用 pandoc 把 docx 转 GFM markdown：
    pandoc input.docx -f docx -t gfm --wrap=none

pandoc 是外部二进制，不进 pyproject。未安装时 raise PandocNotAvailableError，
编排层捕获后 warn 跳过该文件（M1 决策：优雅跳过，先验 PDF/Excel/MD 三类）。

不调 LLM，纯确定性（pandoc 输出确定）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import BaseCleaner, PandocNotAvailableError
from .markdown_cleaner import MarkdownCleaner

__all__ = ["WordCleaner"]


class WordCleaner(BaseCleaner):
    def to_markdown(self, raw_path: Path) -> str:
        if not shutil.which("pandoc"):
            raise PandocNotAvailableError(
                f"pandoc 未安装，跳过 Word 文档: {raw_path}"
            )
        result = subprocess.run(
            ["pandoc", str(raw_path), "-f", "docx", "-t", "gfm", "--wrap=none"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            from .base import CleanerError

            raise CleanerError(
                f"pandoc 转换失败 ({raw_path}): {result.stderr.strip()}"
            )
        # pandoc GFM 输出再做一遍 md 规范化（Setext→ATX）
        return MarkdownCleaner.normalize(result.stdout)

"""Cleaner 基类与异常 —— PRD §6.2。

每个 Cleaner 负责把一种原件（PDF/Word/Excel/MD）清洗成
**ATX 标题（#/##/###）+ pipe 表格** 的 markdown。

契约（对所有 Cleaner）：
- `to_markdown(raw_path) -> str`：纯函数式（不写文件），返回清洗后 md 文本。
- 输出标题用 ATX（#），不用 Setext（下划线式）。
- 表格用 pipe 表（`| a | b |` + `|---|---|` 分隔行）。
- 失败 raise CleanerError（或其子类），由编排层捕获决定跳过/中止。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

__all__ = ["BaseCleaner", "CleanerError", "PandocNotAvailableError"]


class CleanerError(Exception):
    """清洗失败（解析错误、格式不符预期等）。"""


class PandocNotAvailableError(CleanerError):
    """系统未安装 pandoc —— WordCleaner 优雅跳过信号。

    编排层捕获后 warn 跳过该 .docx，不中断批次（PRD §6.2.2 决策）。
    """


class BaseCleaner(ABC):
    """四类 Cleaner 的统一抽象。"""

    @abstractmethod
    def to_markdown(self, raw_path: Path) -> str:
        """返回清洗后 markdown：ATX 标题 + pipe 表格。"""
        raise NotImplementedError

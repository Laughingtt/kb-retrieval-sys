"""Excel（.xlsx）清洗 —— PRD §6.2.3, F4（重中之重）。

读全部 sheet，每 sheet → `## {sheet名}` pipe 表 section。
合并单元格用 ffill 补齐；空 sheet 跳过。

**宽表 F4**：列数 > WIDE_TABLE_THRESHOLD(默认 20) → 字段分组拆子 section
`## {sheet名} — {组名}`；无法分组则按列上限截断。
表 section 豁免 200 行二次切分（SectionSplitter 通过 is_table 标记识别）。

不调 LLM，纯确定性。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import BaseCleaner, CleanerError

__all__ = ["ExcelCleaner"]

WIDE_TABLE_THRESHOLD = 20   # 列数超此 → 宽表处理（F4）
TRUNCATE_COLS = 15          # 无法分组时的列截断上限


class ExcelCleaner(BaseCleaner):
    def to_markdown(self, raw_path: Path) -> str:
        try:
            sheets = pd.read_excel(raw_path, sheet_name=None)
        except Exception as e:
            raise CleanerError(f"读取 Excel 失败 ({raw_path}): {e}") from e

        parts: list[str] = []
        for sheet_name, df in sheets.items():
            parts.append(self._sheet_to_md(str(sheet_name), df))
        return "\n\n".join(p for p in parts if p).rstrip() + "\n"

    def _sheet_to_md(self, sheet_name: str, df: pd.DataFrame) -> str:
        # 空 sheet（无列 或 全空）跳过
        if df is None or df.empty or len(df.columns) == 0:
            return ""
        # 合并单元格补齐：向下填充（pandas 2.x 用 ffill；fillna(method=) 已弃用）
        try:
            df = df.ffill()
        except Exception:
            pass  # ffill 失败则保留原样
        n_cols = len(df.columns)

        if n_cols > WIDE_TABLE_THRESHOLD:
            return self._wide_sheet_to_md(sheet_name, df)

        return self._format_section(sheet_name, df)

    def _format_section(self, title: str, df: pd.DataFrame) -> str:
        """单 sheet → `## {title}` + pipe 表。"""
        table = df.to_markdown(index=False)
        return f"## {title}\n\n{table}"

    def _wide_sheet_to_md(self, sheet_name: str, df: pd.DataFrame) -> str:
        """宽表 F4：字段分组拆子 section；无法分组则列截断。"""
        groups = self._group_columns(list(df.columns))
        if groups:
            parts: list[str] = []
            for group_name, cols in groups.items():
                sub = df[cols]
                parts.append(self._format_section(f"{sheet_name} — {group_name}", sub))
            return "\n\n".join(parts)
        # 兜底：按 TRUNCATE_COLS 截断分批，重复表头
        parts = []
        cols = list(df.columns)
        for i in range(0, len(cols), TRUNCATE_COLS):
            batch = cols[i : i + TRUNCATE_COLS]
            sub = df[batch]
            label = f"{sheet_name} — 列{i + 1}-{i + len(batch)}"
            parts.append(self._format_section(label, sub))
        return "\n\n".join(parts)

    @staticmethod
    def _group_columns(columns: list[str]) -> dict[str, list[str]]:
        """按列名前缀（首个 `_` 前或整体）分组。

        例：order_id/order_name → 组 order；amount_total/amount_tax → 组 amount。
        只剩一组的（无明显前缀）返回空 dict，触发兜底截断。
        """
        groups: dict[str, list[str]] = {}
        for col in columns:
            col_str = str(col)
            prefix = col_str.split("_", 1)[0] if "_" in col_str else col_str
            groups.setdefault(prefix, []).append(col)
        # 单组 = 无明显分组价值 → 退兜底
        if len(groups) <= 1:
            return {}
        return groups

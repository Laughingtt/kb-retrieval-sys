"""PDF 清洗 —— PRD §6.2.1, F3。

权威路径：`pymupdf4llm.to_markdown(raw_path)` → ATX 标题 + pipe 表。
兜底路径：当权威输出表格残缺（行数<2 或空格占比过高）时，
用 `pdfplumber.extract_tables()` 抽该页表，转 pipe 表按页就近插入。

F3 原则：不做坐标强对齐合并，只做「权威 + 残缺检测 + 兜底抽取」。

不调 LLM，纯确定性。
"""

from __future__ import annotations

from pathlib import Path

from .base import BaseCleaner, CleanerError

__all__ = ["PdfCleaner"]

# 表格残缺启发式阈值
MIN_TABLE_ROWS = 2          # pipe 表行数 <2 视为残缺
HIGH_WHITESPACE_RATIO = 0.6  # 表格行空格占比超此 → 残缺


class PdfCleaner(BaseCleaner):
    def to_markdown(self, raw_path: Path) -> str:
        try:
            import pymupdf4llm  # type: ignore
        except Exception as e:
            raise CleanerError(f"pymupdf4llm 不可用: {e}") from e

        try:
            md_text: str = pymupdf4llm.to_markdown(str(raw_path))
        except Exception as e:
            raise CleanerError(f"PyMuPDF4LLM 解析失败 ({raw_path}): {e}") from e

        if self._needs_fallback(md_text):
            md_text = self._apply_fallback(raw_path, md_text)

        return md_text.rstrip() + "\n"

    @staticmethod
    def _needs_fallback(md_text: str) -> bool:
        """权威输出表格残缺启发式：检测 pipe 表行数过少或空格占比过高。"""
        lines = md_text.splitlines()
        table_rows = [ln for ln in lines if ln.lstrip().startswith("|")]
        # 没有表格不触发兜底（纯文本 PDF 无需兜底）
        if not table_rows:
            return False
        if len(table_rows) < MIN_TABLE_ROWS:
            return True
        # 空格占比过高 → 表格结构散乱
        joined = "".join(table_rows)
        if joined and (joined.count(" ") / len(joined)) > HIGH_WHITESPACE_RATIO:
            return True
        return False

    @staticmethod
    def _apply_fallback(raw_path: Path, md_text: str) -> str:
        """用 pdfplumber 抽表格，转 pipe 表追加到 md 末尾（按页就近，不做坐标合并）。"""
        try:
            import pdfplumber  # type: ignore
        except Exception:
            # pdfplumber 不可用 → 返回权威输出（已尽力）
            return md_text

        extra: list[str] = ["", "## 补充表格（pdfplumber 兜底抽取）", ""]
        found = False
        with pdfplumber.open(str(raw_path)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []
                for t_idx, table in enumerate(tables):
                    if not table or len(table) < MIN_TABLE_ROWS:
                        continue
                    extra.append(f"### 第{page_no}页 表{t_idx + 1}")
                    extra.append("")
                    extra.append(_table_to_pipe(table))
                    extra.append("")
                    found = True
        if found:
            return md_text.rstrip() + "\n" + "\n".join(extra) + "\n"
        return md_text


def _table_to_pipe(table: list[list]) -> str:
    """二维列表 → pipe 表（首行为表头 + 分隔行）。"""
    if not table:
        return ""
    header = table[0]
    body = table[1:]
    cols = max(len(r) for r in table)

    def fmt_row(row: list) -> str:
        cells = [str(c).strip().replace("\n", " ") if c is not None else "" for c in row]
        # 补齐列数
        cells += [""] * (cols - len(cells))
        return "| " + " | ".join(cells) + " |"

    sep = "| " + " | ".join("---" for _ in range(cols)) + " |"
    rows = [fmt_row(header), sep] + [fmt_row(r) for r in body]
    return "\n".join(rows)

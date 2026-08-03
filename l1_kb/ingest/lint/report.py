# l1_kb/ingest/lint/report.py
"""lint_report.json 落盘 + 终端摘要 + 退出码 —— M3 设计 §四。"""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from .checker import LintReport

__all__ = ["write_report", "format_summary", "exit_code"]

LEVEL_ICON = {"error": "✗", "warn": "⚠", "info": "ℹ"}


def write_report(report: LintReport, out_path: Path) -> None:
    """原子写 lint_report.json（可 CI/diff）。"""
    payload = {
        "ts": report.ts,
        "errors": report.errors,
        "warnings": report.warnings,
        "info": report.info,
        "issues": [asdict(i) for i in report.issues],
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def format_summary(report: LintReport) -> str:
    """终端人读多行摘要。"""
    lines = [
        f"Lint 报告（{report.ts}）: errors: {report.errors}, warnings: {report.warnings}, info: {report.info}",
    ]
    for i in report.issues:
        loc = f" [{i.page}]" if i.page else (f" [{i.type}]" if i.type else "")
        lines.append(f"  {LEVEL_ICON.get(i.level, '?')} {i.code}{loc}: {i.msg}")
    return "\n".join(lines)


def exit_code(report: LintReport) -> int:
    """error 级项 → 退出码 1，否则 0。"""
    return 1 if report.errors else 0

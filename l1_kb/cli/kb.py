"""kb CLI 入口 —— PRD §11。

M1 子命令：
    kb clean <path>           # 单文件或目录（递归）清洗 → md/
    kb clean <path> --dry-run # 只打印 doc_id + sections 概要，不写 md/

批处理目录：递归遍历，每文件过 clean_one。
- PandocNotAvailableError → warn 跳过，不中断批次。
- 路径不安全 → warn 跳过。
- 其他 CleanerError → 记 error，继续（不中止整批）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..ingest.clean import clean_one
from ..ingest.cleaners.base import CleanerError
from ..ingest.cleaners.dispatcher import SUPPORTED_EXTS

DEFAULT_RAW = "l1_kb/knowledge_base/raw"
DEFAULT_MD = "l1_kb/knowledge_base/md"


@click.group()
def cli() -> None:
    """L1 知识库层 CLI。"""


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--md-root",
    "md_root",
    type=click.Path(path_type=Path),
    default=DEFAULT_MD,
    help="清洗产物 md/ 根目录。",
)
@click.option(
    "--raw-root",
    "raw_root",
    type=click.Path(path_type=Path),
    default=DEFAULT_RAW,
    help="raw/ 根目录（用于 doc_id 派生与路径校验的基准）。",
)
@click.option("--dry-run", is_flag=True, help="只打印概要，不写 md/。")
def clean(path: Path, md_root: Path, raw_root: Path, dry_run: bool) -> None:
    """清洗 PATH（单文件或目录）→ md/。

    PATH 是文件时，raw_root 用于相对路径计算（默认 l1_kb/knowledge_base/raw）。
    """
    raw_root = raw_root.resolve()
    md_root = md_root.resolve()
    path = path.resolve()

    files: list[Path]
    if path.is_file():
        files = [path]
    else:
        files = sorted(
            p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )

    if not files:
        click.echo(f"未找到可清洗文件（支持: {', '.join(SUPPORTED_EXTS)}）: {path}")
        return

    ok = 0
    skipped = 0
    failed = 0
    for f in files:
        try:
            result = clean_one(raw_root, f, md_root, dry_run=dry_run)
        except CleanerError as e:
            click.secho(f"[ERROR] {f}: {e}", err=True, fg="red")
            failed += 1
            continue
        if result.skipped:
            click.secho(f"[SKIP] {f}: {result.reason}", fg="yellow")
            skipped += 1
            continue
        click.secho(
            f"[OK] {f.name} → doc_id={result.doc_id} "
            f"category={result.category} sections={len(result.sections)}",
            fg="green",
        )
        if dry_run:
            for s in result.sections:
                click.echo(f"      {s.section_id} L{s.line_start}-{s.line_end} "
                           f"(L{s.level}) {'[表]' if s.is_table else ''} {s.title}")
        ok += 1

    click.echo(
        f"\n完成: 成功 {ok}, 跳过 {skipped}, 失败 {failed} (共 {len(files)} 文件)"
        + (" [dry-run]" if dry_run else "")
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    cli()

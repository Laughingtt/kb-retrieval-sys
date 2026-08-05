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
from ..ingest.wiki import ingest as wiki_ingest
from ..ingest.wiki.index_log import rebuild_index
from ..ingest.wiki.ingest import ingest_source, make_client_from_config, read_index_md
from ..ingest.incremental import ingest_flow, change_detect, delete as incr_delete
from ..ingest.incremental import hash_store, ingest_log
from ..ingest.lint import checker as lint_checker, report as lint_report
from ..ingest.doc_id import make_doc_id
from .. import config

DEFAULT_RAW = "l1_kb/knowledge_base/raw"
DEFAULT_MD = "l1_kb/knowledge_base/md"
DEFAULT_WIKI = "l1_kb/knowledge_base/wiki"
DEFAULT_CACHE = "l1_kb/knowledge_base/.cache/ingest-cache.json"
DEFAULT_HASH = "l1_kb/knowledge_base/.cache/hash.json"
DEFAULT_LOG = "l1_kb/knowledge_base/ingest_log.jsonl"
DEFAULT_LINT_REPORT = "lint_report.json"


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


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--hash-path", "hash_path", type=click.Path(path_type=Path), default=DEFAULT_HASH)
@click.option("--log-path", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--no-llm", is_flag=True, help="禁用 LLM，强制 fallback。")
def ingest(path, md_root, raw_root, wiki_root, cache_path, hash_path, log_path, no_llm):
    """摄入 PATH。PATH 在 raw_root 下 → raw 三态增量；在 md_root 下 → M2 直摄入。"""
    raw_root = raw_root.resolve(); md_root = md_root.resolve()
    wiki_root = wiki_root.resolve(); cache_path = cache_path.resolve()
    hash_path = hash_path.resolve(); log_path = log_path.resolve()
    path = path.resolve()
    if raw_root in path.parents or path == raw_root:
        client = None if no_llm else make_client_from_config()
        if client is None:
            click.secho("[info] LLM 不可用或 --no-llm，走确定性 fallback", fg="yellow")
        summary = ingest_flow.run_incremental(
            raw_root=raw_root, md_root=md_root, wiki_root=wiki_root,
            cache_path=cache_path, hash_path=hash_path, log_path=log_path,
            client=client, today=config.today(),
        )
        for d in summary.details:
            click.echo(d)
        click.echo(f"\n完成: 新增 {summary.added}, 修改 {summary.modified}, "
                  f"删除 {summary.deleted}, 跳过 {summary.skipped}, 失败 {summary.failed} "
                  f"(共 {summary.total} 文件)")
        if summary.failed:
            sys.exit(1)
        return
    # —— M2 向后兼容：md 直摄入 ——
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*.md") if p.is_file())
    if not files:
        click.echo(f"未找到 md 文件: {path}"); return
    client = None if no_llm else make_client_from_config()
    if client is None:
        click.secho("[info] LLM 不可用或 --no-llm，走确定性 fallback", fg="yellow")
    ok = skipped = failed = 0
    for f in files:
        try:
            rel = f.relative_to(md_root) if md_root in f.parents else f
        except ValueError:
            rel = f
        identity = str(rel).replace("\\", "/")
        index_md = read_index_md(wiki_root)
        today = config.today()
        try:
            res = ingest_source(f, identity, wiki_root=wiki_root, cache_path=cache_path, client=client, today=today, index_md=index_md)
        except Exception as e:
            click.secho(f"[ERR] {f.name}: {e}", fg="red", err=True); failed += 1; continue
        if res.skipped_cached:
            click.secho(f"[SKIP-CACHED] {f.name}", fg="cyan"); skipped += 1
        else:
            tag = "[FALLBACK]" if res.fallback else "[LLM]"
            click.secho(f"{tag} {f.name} → 写入 {len(res.written_paths)} 页", fg="green"); ok += 1
    click.echo(f"\n完成: 摄入 {ok}, 缓存跳过 {skipped}, 失败 {failed} (共 {len(files)} 文件)")


@cli.command(name="index")
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
def index_cmd(wiki_root: Path) -> None:
    """重建 wiki/index.md（确定性）。"""
    wiki_root = wiki_root.resolve()
    rebuild_index(wiki_root, config.today())
    click.secho(f"[OK] 已重建 {wiki_root / 'index.md'}", fg="green")


@cli.command()
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--hash-path", "hash_path", type=click.Path(path_type=Path), default=DEFAULT_HASH)
@click.option("--log-path", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=DEFAULT_LINT_REPORT)
def lint(wiki_root, raw_root, md_root, cache_path, hash_path, log_path, out_path):
    """五项确定性自检 → lint_report.json + 终端摘要；error→退码 1。"""
    today = config.today()
    report = lint_checker.run_lint(
        wiki_root=wiki_root.resolve(), hash_path=hash_path.resolve(),
        ingest_log_path=log_path.resolve(), cache_path=cache_path.resolve(),
        md_root=md_root.resolve(), today=today,
    )
    lint_report.write_report(report, out_path.resolve())
    click.echo(lint_report.format_summary(report))
    click.secho(f"[OK] 报告已写: {out_path}", fg="green")
    ingest_log.append_lint(log_path.resolve(), today=today,
                            issues=len(report.issues), errors=report.errors,
                            warnings=report.warnings, info=report.info)
    sys.exit(lint_report.exit_code(report))


@cli.command()
@click.argument("query")
@click.option("--top-k", default=10, show_default=True, type=int)
def search(query, top_k):
    """BM25 检索 wiki 知识页。"""
    from l1_kb.service.store import load_store
    from l1_kb.service.search import search as svc_search
    store = load_store(config.WIKI_ROOT)
    hits = svc_search(store, query, top_k=top_k)
    if not hits:
        click.echo("无结果")
        return
    for h in hits:
        click.echo(f"[{h.score:.4f}] {h.doc_id} / {h.section_id} — {h.title}")
        if h.snippet:
            for ln in h.snippet.splitlines():
                click.echo(f"    {ln}")


@cli.command()
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--hash-path", "hash_path", type=click.Path(path_type=Path), default=DEFAULT_HASH)
@click.option("--log-path", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--yes", is_flag=True, help="确认清空生成物（否则仅 dry-run）。")
def rebuild(raw_root, md_root, wiki_root, cache_path, hash_path, log_path, yes):
    """清生成物从 raw 全量重建（需 --yes）。"""
    raw_root = raw_root.resolve(); md_root = md_root.resolve()
    wiki_root = wiki_root.resolve(); cache_path = cache_path.resolve()
    hash_path = hash_path.resolve(); log_path = log_path.resolve()
    if not yes:
        click.echo("[dry-run] 将清空: md/ wiki/ ingest-cache.json hash.json ingest_log.jsonl；raw/ 不动。")
        click.echo("        加 --yes 执行全量重建。")
        return
    client = make_client_from_config()
    if client is None:
        click.secho("[info] LLM 不可用，走确定性 fallback", fg="yellow")
    summary = ingest_flow.rebuild_all(
        raw_root=raw_root, md_root=md_root, wiki_root=wiki_root,
        cache_path=cache_path, hash_path=hash_path, log_path=log_path,
        client=client, today=config.today(),
    )
    for d in summary.details:
        click.echo(d)
    click.secho(f"[OK] 全量重建完成: {summary.added} 摄入", fg="green")


if __name__ == "__main__":
    cli()

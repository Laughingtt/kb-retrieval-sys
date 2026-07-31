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
from ..ingest.section_splitter import split as split_sections
from ..retrieval.bm25 import BM25Retriever
from ..retrieval.base import RRFFuser
from ..retrieval.snippet import make_snippet
from .. import config

DEFAULT_RAW = "l1_kb/knowledge_base/raw"
DEFAULT_MD = "l1_kb/knowledge_base/md"
DEFAULT_WIKI = "l1_kb/knowledge_base/wiki"
DEFAULT_CACHE = "l1_kb/knowledge_base/.cache/ingest-cache.json"


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


def _wiki_entries(wiki_root: Path) -> list[dict]:
    """扫描 wiki/*.md → section entries（复用 M1 splitter）。"""
    entries = []
    if not wiki_root.exists():
        return entries
    for p in sorted(wiki_root.rglob("*.md")):
        if p.stem in ("index", "log", "overview"):
            continue
        text = p.read_text(encoding="utf-8")
        # 解析 frontmatter 取 title
        from ..ingest.wiki.frontmatter import parse as parse_fm
        fm, body = parse_fm(text)
        full = (fm.title + "\n\n" + body) if fm.title else body
        for s in split_sections(full):
            seg_lines = full.splitlines()
            body_text = "\n".join(seg_lines[s.line_start - 1 : s.line_end])
            entries.append({
                "slug": p.stem,
                "section_id": s.section_id,
                "title": f"{fm.title} / {s.title}" if s.title else fm.title,
                "body_text": body_text,
                "_line_start": s.line_start,
                "_line_end": s.line_end,
                "_text": text,
            })
    return entries


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--md-root", "md_root", type=click.Path(path_type=Path), default=DEFAULT_MD)
@click.option("--raw-root", "raw_root", type=click.Path(path_type=Path), default=DEFAULT_RAW)
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--cache-path", "cache_path", type=click.Path(path_type=Path), default=DEFAULT_CACHE)
@click.option("--no-llm", is_flag=True, help="禁用 LLM，强制 fallback。")
def ingest(path: Path, md_root: Path, raw_root: Path, wiki_root: Path, cache_path: Path, no_llm: bool) -> None:
    """摄入 md 文件（单文件或目录）→ wiki 页 + index/log。

    无 LLM key 或 --no-llm 时走确定性 fallback（仅产 source 摘要页）。
    """
    wiki_root = wiki_root.resolve()
    cache_path = cache_path.resolve()
    raw_root = raw_root.resolve()
    path = path.resolve()

    files = [path] if path.is_file() else sorted(p for p in path.rglob("*.md") if p.is_file())
    if not files:
        click.echo(f"未找到 md 文件: {path}")
        return

    client = None if no_llm else make_client_from_config()
    if client is None:
        click.secho("[info] LLM 不可用或 --no-llm，走确定性 fallback", fg="yellow")

    ok = skipped = failed = 0
    for f in files:
        # source_identity：相对 raw_root 的路径（含扩展名）；md 文件名是 {slug}__{hash}.md
        # 简化：用 md 相对 md_root 的路径作为 identity 近似（M1 doc_id 已稳定）
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
            click.secho(f"[ERR] {f.name}: {e}", fg="red", err=True)
            failed += 1
            continue
        if res.skipped_cached:
            click.secho(f"[SKIP-CACHED] {f.name}", fg="cyan")
            skipped += 1
        else:
            tag = "[FALLBACK]" if res.fallback else "[LLM]"
            click.secho(f"{tag} {f.name} → 写入 {len(res.written_paths)} 页", fg="green")
            ok += 1
    click.echo(f"\n完成: 摄入 {ok}, 缓存跳过 {skipped}, 失败 {failed} (共 {len(files)} 文件)")


@cli.command(name="index")
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
def index_cmd(wiki_root: Path) -> None:
    """重建 wiki/index.md（确定性）。"""
    wiki_root = wiki_root.resolve()
    rebuild_index(wiki_root, config.today())
    click.secho(f"[OK] 已重建 {wiki_root / 'index.md'}", fg="green")


@cli.command()
@click.argument("query")
@click.option("--wiki-root", "wiki_root", type=click.Path(path_type=Path), default=DEFAULT_WIKI)
@click.option("--top-k", default=10, help="返回条数。")
def search(query: str, wiki_root: Path, top_k: int) -> None:
    """BM25 检索 wiki 页（RRF 单路直通）。"""
    wiki_root = wiki_root.resolve()
    entries = _wiki_entries(wiki_root)
    bm25 = BM25Retriever([
        {"slug": e["slug"], "section_id": e["section_id"], "title": e["title"], "body_text": e["body_text"]}
        for e in entries
    ])
    hits = bm25.search(query, top_n=50)
    fused = RRFFuser().fuse([hits], k=60, top_k=top_k)
    if not fused:
        click.echo("(无结果)")
        return
    for i, h in enumerate(fused, 1):
        # 填 snippet：找对应 entry 的原文
        e = next((x for x in entries if x["slug"] == h.doc_id and x["section_id"] == h.section_id), None)
        snippet = make_snippet(e["_text"], e["_line_start"], e["_line_end"]) if e else ""
        click.secho(f"[#{i}] score={h.score:.4f}  {h.doc_id} / {h.section_id}", fg="green")
        for line in snippet.splitlines()[:3]:
            click.echo(f"     {line}")
        click.echo(f"     [{h.source}]")


if __name__ == "__main__":
    cli()

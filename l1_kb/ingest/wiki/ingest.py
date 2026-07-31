"""复利 wiki 摄入编排 —— M2 设计 §3。

吸收 llm_wiki ingest.ts 两步流（step1 分析 → step2 生成 FILE block → 解析 →
写入/合并 → 重建 index/log）。LLM 不可用时确定性 fallback 仅产 source 摘要页。
理解原理后用 Python 重新实现，非复制 llm_wiki 源码。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...llm.client import LLMClient, LLMError
from ...llm.ingest_prompts import build_step1_messages, build_step2_messages
from ..section_splitter import split as split_sections
from .file_blocks import parse_file_blocks
from .index_log import append_log, rebuild_index
from .ingest_cache import check_cache, content_hash, save_cache
from .merge import merge_page
from .page_types import normalize_wiki_path, slug_from_source_identity

__all__ = ["IngestResult", "ingest_source", "build_fallback_pages", "read_index_md", "make_client_from_config"]


def _warn(msg: str) -> None:
    print(f"[warn] ingest: {msg}", file=sys.stderr)


@dataclass
class IngestResult:
    written_paths: list[str] = field(default_factory=list)
    skipped_cached: bool = False
    fallback: bool = False
    errors: list[str] = field(default_factory=list)


def read_index_md(wiki_root: Path) -> str:
    idx = wiki_root / "index.md"
    if idx.exists():
        return idx.read_text(encoding="utf-8")
    return "# Wiki Index\n_(暂无页面)_\n"


def make_client_from_config() -> LLMClient | None:
    """从 config 构造 LLMClient；未配置 key 返回 None。"""
    from ... import config

    if not config.llm_enabled():
        return None
    try:
        return LLMClient(config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL)
    except Exception as e:  # 构造失败（如网络/库问题）
        _warn(f"LLM client 构造失败，走 fallback: {e}")
        return None


def build_fallback_pages(source_identity: str, md_text: str, today: str) -> list[tuple[str, str]]:
    """确定性回退：仅产 1 张 source 摘要页（吸收 llm_wiki buildFallbackSourceSummary 原理）。

    body ← M1 sections 拼接的标题 + 首段；title ← Source: {identity}；
    sources=[identity]；tags/related 空。
    """
    slug = slug_from_source_identity(source_identity)
    path = f"wiki/sources/{slug}.md"
    sections = split_sections(md_text)
    body_parts = []
    for s in sections:
        if s.title:
            body_parts.append(f"## {s.title}")
        # 取该 section 的首段正文
        lines = md_text.splitlines()
        seg = lines[s.line_start - 1 : s.line_end]
        body_parts.append("\n".join(seg).strip())
    body = "\n\n".join(p for p in body_parts if p) or "(Analysis not available)"
    fm = (
        "---\n"
        f"type: source\n"
        f'title: "Source: {source_identity}"\n'
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: []\n"
        "related: []\n"
        f"sources: [{source_identity}]\n"
        "---\n\n"
    )
    return [(path, fm + body + "\n")]


def ingest_source(
    md_path: Path,
    source_identity: str,
    *,
    wiki_root: Path,
    cache_path: Path,
    client: LLMClient | None,
    today: str,
    index_md: str,
) -> IngestResult:
    """摄入单份 md → wiki 页 + 合并 + 重建 index/log。"""
    md_text = md_path.read_text(encoding="utf-8")
    chash = content_hash(md_text)

    # cache 命中跳过两步 LLM
    if check_cache(cache_path, source_identity, chash):
        return IngestResult(skipped_cached=True)

    # 决定 pages：LLM 两步 或 fallback
    pages: list[tuple[str, str]] | None = None
    fallback = False
    if client is not None:
        try:
            pages = _two_step_llm(client, source_identity, md_text, index_md)
        except Exception as e:  # noqa: BLE001
            _warn(f"LLM 两步失败，走 fallback: {e}")
            pages = None
    if pages is None:
        pages = build_fallback_pages(source_identity, md_text, today)
        fallback = True

    # 写入/合并每页
    wiki_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for path, content in pages:
        # path 形如 wiki/sources/{slug}.md；写入时剥去 wiki/ 前缀，
        # 使落盘位置为 wiki_root/sources/{slug}.md（与 index_log/rebuild_index
        # 的 rglob 期望一致）。routing 校验仍用原始 path（validate_routing 要求 wiki/ 前缀）。
        # 归一化已知 LLM 漂移别名目录（processes→process），让复数目录真正落盘到单数。
        path = normalize_wiki_path(path)
        rel = path
        if rel.startswith("wiki/"):
            rel = rel[len("wiki/"):]
        full = wiki_root / rel
        exists = full.exists()
        existing_text = full.read_text(encoding="utf-8") if exists else None
        merged = merge_page(existing_text, path, content, source_identity, today, exists=exists)
        if merged is None:
            continue  # routing 不一致已 warn
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(merged, encoding="utf-8")
        written.append(str(full))

    # 重建 index + 追加 log
    rebuild_index(wiki_root, today)
    append_log(wiki_root, source_identity, today)

    save_cache(cache_path, source_identity, chash, written)
    return IngestResult(written_paths=written, fallback=fallback)


def _two_step_llm(
    client: LLMClient, source_identity: str, md_text: str, index_md: str
) -> list[tuple[str, str]]:
    """两步 LLM：step1 分析 JSON → step2 FILE block。"""
    sys1, user1 = build_step1_messages(source_identity, md_text, index_md)
    step1 = client.chat_json(sys1, user1)
    # exists 交叉校验：纠正幻觉（实际磁盘 slug 集合）——此处仅透传，校验在 step2 prompt 已注入 index
    sys2, user2 = build_step2_messages(source_identity, md_text, step1, index_md)
    step2_text = client.chat_text(sys2, user2)
    blocks = parse_file_blocks(step2_text)
    if not blocks:
        raise LLMError("step2 未产出任何合法 FILE block")
    return blocks

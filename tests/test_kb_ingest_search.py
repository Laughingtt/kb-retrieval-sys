import os
from pathlib import Path

from click.testing import CliRunner

from l1_kb.cli.kb import cli


def _make_md(root):
    md = root / "data_table" / "order_detail.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        "## 订单\n\n| order_id | customer |\n|---|---|\n| O1 | 张三 |\n\n"
        "## 订单明细\n\n| order_id | item |\n|---|---|\n| O1 | 笔记本 |\n",
        encoding="utf-8",
    )
    return md


def test_kb_ingest_fallback_then_search(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    md_root = tmp_path / "md"
    _make_md(md_root)
    md_path = md_root / "data_table" / "order_detail.md"

    runner = CliRunner()
    # ingest（无 LLM key → fallback）
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = runner.invoke(cli, [
        "ingest", str(md_path),
        "--md-root", str(md_root),
        "--raw-root", str(tmp_path / "raw"),
        "--wiki-root", str(wiki),
        "--cache-path", str(tmp_path / "cache.json"),
    ])
    assert res.exit_code == 0, res.output
    assert (wiki / "sources").exists()
    assert (wiki / "index.md").exists()

    # index 重建
    res2 = runner.invoke(cli, ["index", "--wiki-root", str(wiki)])
    assert res2.exit_code == 0

    # search order_id → 命中
    res3 = runner.invoke(cli, ["search", "order_id", "--wiki-root", str(wiki)])
    assert res3.exit_code == 0
    assert "order_id" in res3.output


def test_kb_search_empty_wiki(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    runner = CliRunner()
    res = runner.invoke(cli, ["search", "order_id", "--wiki-root", str(wiki)])
    assert res.exit_code == 0  # 空语料不崩

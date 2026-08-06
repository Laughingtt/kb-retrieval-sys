import os
from pathlib import Path

from click.testing import CliRunner

from kb_retrieval.kb.cli.kb import cli


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

    # search order_id → 命中（search 走 config.WIKI_ROOT，用 env 指向 tmp wiki）
    monkeypatch.setenv("WIKI_ROOT", str(wiki))
    res3 = runner.invoke(cli, ["search", "order_id"])
    assert res3.exit_code == 0
    assert "order_id" in res3.output


def test_ingest_cmd_continues_on_error(tmp_path, monkeypatch):
    """单文件 ingest_source 抛异常时，CLI 应记 failed、continue、不崩批次。"""
    wiki = tmp_path / "wiki"
    md_root = tmp_path / "md"

    # 两份 md 文件
    md_ok = md_root / "data_table" / "order_detail.md"
    md_ok.parent.mkdir(parents=True, exist_ok=True)
    md_ok.write_text("## 订单\n\n| order_id | customer |\n|---|---|\n| O1 | 张三 |\n", encoding="utf-8")
    md_bad = md_root / "data_table" / "broken.md"
    md_bad.write_text("## 坏\n\n| x |\n|---|\n| 1 |\n", encoding="utf-8")

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    # 替换 ingest_source：对 broken.md 抛异常，其余走原逻辑（fallback）
    from kb_retrieval.kb.cli import kb as kb_mod
    real_ingest_source = kb_mod.ingest_source

    def fake_ingest_source(f, identity, **kwargs):
        if f.name == "broken.md":
            raise RuntimeError("boom")
        return real_ingest_source(f, identity, **kwargs)

    monkeypatch.setattr(kb_mod, "ingest_source", fake_ingest_source)

    runner = CliRunner()
    res = runner.invoke(cli, [
        "ingest", str(md_root),
        "--md-root", str(md_root),
        "--raw-root", str(tmp_path / "raw"),
        "--wiki-root", str(wiki),
        "--cache-path", str(tmp_path / "cache.json"),
    ])
    # 批次未崩：退出码 0（ingest 不加 sys.exit），且输出含 ERR + 失败 1
    assert res.exit_code == 0, res.output
    assert "[ERR]" in res.output
    assert "broken.md" in res.output
    assert "失败 1" in res.output
    # 另一份仍被正常处理
    assert "失败 0" not in res.output


def test_kb_search_empty_wiki(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("WIKI_ROOT", str(wiki))
    runner = CliRunner()
    res = runner.invoke(cli, ["search", "order_id"])
    assert res.exit_code == 0  # 空语料不崩

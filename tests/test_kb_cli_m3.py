# tests/test_kb_cli_m3.py
import json
from pathlib import Path
from click.testing import CliRunner
from kb_retrieval.kb.cli.kb import cli

def _make_raw_md(tmp_path: Path):
    raw = tmp_path / "raw" / "data_table"
    raw.mkdir(parents=True)
    f = raw / "order_detail.xlsx"
    f.write_bytes(b"hello")
    md_root = tmp_path / "md"
    (md_root / "data_table").mkdir(parents=True)
    md_path = md_root / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    md_path.write_text("## 订单\n\n| order_id |\n|---|\n| O1 |\n", encoding="utf-8")
    return f, md_path

def test_kb_ingest_raw_three_state_add(tmp_path, monkeypatch):
    f, md_path = _make_raw_md(tmp_path)
    wiki = tmp_path / "wiki"; wiki.mkdir()
    cache = tmp_path / "cache.json"; hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "ingest", str(tmp_path / "raw"),
        "--raw-root", str(tmp_path / "raw"),
        "--md-root", str(tmp_path / "md"),
        "--wiki-root", str(wiki),
        "--cache-path", str(cache),
        "--hash-path", str(hp), "--log-path", str(lp),
    ])
    assert res.exit_code == 0, res.output
    assert "新增 1" in res.output
    data = json.loads(hp.read_text(encoding="utf-8"))
    assert "data_table_order_detail" in data
    assert '"type": "ingest"' in lp.read_text(encoding="utf-8")

def test_kb_ingest_md_backward_compat(tmp_path, monkeypatch):
    # path 在 md_root 下 → 走 M2 直摄入，无 hash.json
    md_root = tmp_path / "md"
    (md_root / "data_table").mkdir(parents=True)
    md_path = md_root / "data_table" / "order_detail.md"
    md_path.write_text("## 订单\n\n| order_id |\n|---|\n| O1 |\n", encoding="utf-8")
    wiki = tmp_path / "wiki"; wiki.mkdir()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "ingest", str(md_path),
        "--raw-root", str(tmp_path / "raw"),
        "--md-root", str(md_root),
        "--wiki-root", str(wiki),
        "--cache-path", str(tmp_path / "cache.json"),
    ])
    assert res.exit_code == 0, res.output
    assert (wiki / "sources").exists()

def test_kb_lint_clean_exit0(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "sources").mkdir(parents=True)
    (wiki / "sources" / "s1.md").write_text("---\ntype: source\ntitle: t\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: []\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    wiki.joinpath("index.md").write_text("# Wiki Index\n\n## source\n\n- [[s1|t]]\n", encoding="utf-8")
    wiki.joinpath("log.md").write_text("# Wiki Log\n", encoding="utf-8")
    res = CliRunner().invoke(cli, [
        "lint", "--wiki-root", str(wiki),
        "--raw-root", str(tmp_path / "raw"), "--md-root", str(tmp_path / "md"),
        "--cache-path", str(tmp_path / "c.json"),
        "--hash-path", str(tmp_path / "h.json"), "--log-path", str(tmp_path / "l.jsonl"),
        "--out", str(tmp_path / "lint_report.json"),
    ])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "lint_report.json").exists()

def test_kb_rebuild_dry_run_no_yes(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "rebuild", "--raw-root", str(tmp_path / "raw"),
        "--md-root", str(tmp_path / "md"), "--wiki-root", str(tmp_path / "wiki"),
        "--cache-path", str(tmp_path / "c.json"),
        "--hash-path", str(tmp_path / "h.json"), "--log-path", str(tmp_path / "l.jsonl"),
    ])
    # 无 --yes → dry-run，不写生成物，退码 0
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output.lower() or "将清空" in res.output
    assert not (tmp_path / "wiki").exists() or not any((tmp_path / "wiki").rglob("*.md"))

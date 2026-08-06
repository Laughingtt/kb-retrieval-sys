from pathlib import Path
from click.testing import CliRunner


def _wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "sources" / "order__a3f9c1e2.md").write_text(
        "---\ntype: source\ntitle: 订单表\n---\n"
        "# 订单表\n\norder_id 主键, order_amount 金额。\n", encoding="utf-8"
    )


def test_kb_search_uses_service(tmp_path, monkeypatch):
    _wiki(tmp_path)
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    from kb_retrieval.kb.cli.kb import cli
    r = CliRunner().invoke(cli, ["search", "订单"])
    assert r.exit_code == 0
    assert "order__a3f9c1e2" in r.output


def test_kb_search_no_match(tmp_path, monkeypatch):
    _wiki(tmp_path)
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    from kb_retrieval.kb.cli.kb import cli
    r = CliRunner().invoke(cli, ["search", "zzznomatch"])
    assert r.exit_code == 0
    assert "无结果" in r.output or r.output.strip() == "" or "0" in r.output

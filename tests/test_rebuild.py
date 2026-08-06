# tests/test_rebuild.py
from pathlib import Path
from click.testing import CliRunner
from kb_retrieval.kb.cli.kb import cli
from kb_retrieval.kb.ingest.incremental import ingest_flow, hash_store
from kb_retrieval.kb.ingest.cleaners.dispatcher import SUPPORTED_EXTS

def _seed_raw(tmp_path: Path):
    raw = tmp_path / "raw"
    (raw / "data_table").mkdir(parents=True)
    f = raw / "data_table" / "order_detail.xlsx"
    # 写一个最小合法 xlsx（b"hi" 不是合法 xlsx，ExcelCleaner 会 raise CleanerError
    # → rebuild_all 的 clean 步失败、ingest 无 md → added=0）。用 openpyxl 造一个
    # 单 sheet 单行的合法表，保证 clean → md → ingest 全链路可走。
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "订单"
    ws.append(["order_id", "customer"])
    ws.append(["O1", "张三"])
    wb.save(f)
    return raw

def test_rebuild_all_idempotent(tmp_path, monkeypatch):
    raw = _seed_raw(tmp_path)
    md_root = tmp_path / "md"; wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"; hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    raw_bytes = (raw / "data_table" / "order_detail.xlsx").read_bytes()
    s1 = ingest_flow.rebuild_all(raw_root=raw, md_root=md_root, wiki_root=wiki,
        cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert s1.added == 1
    assert (wiki / "sources").exists()
    assert "data_table_order_detail" in hash_store.load_hash(hp)
    first_log = lp.read_text(encoding="utf-8")
    # 再跑一次：幂等，仍 1 份摄入
    s2 = ingest_flow.rebuild_all(raw_root=raw, md_root=md_root, wiki_root=wiki,
        cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert s2.added == 1
    # raw 未动
    assert (raw / "data_table" / "order_detail.xlsx").read_bytes() == raw_bytes

def test_kb_rebuild_yes_full(tmp_path, monkeypatch):
    raw = _seed_raw(tmp_path)
    md_root = tmp_path / "md"; wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"; hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = CliRunner().invoke(cli, [
        "rebuild", "--raw-root", str(raw),
        "--md-root", str(md_root), "--wiki-root", str(wiki),
        "--cache-path", str(cache),
        "--hash-path", str(hp), "--log-path", str(lp), "--yes",
    ])
    assert res.exit_code == 0, res.output
    assert (wiki / "sources").exists()
    assert "data_table_order_detail" in hash_store.load_hash(hp)
    assert "type\": \"rebuild" in lp.read_text(encoding="utf-8") or 'type": "rebuild' in lp.read_text(encoding="utf-8")

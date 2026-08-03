# tests/test_ingest_flow.py
from pathlib import Path
from unittest.mock import MagicMock
from l1_kb.ingest.incremental import ingest_flow, hash_store
from l1_kb.ingest.wiki.ingest import build_fallback_pages
from l1_kb.ingest.wiki.page_types import slug_from_source_identity

def _seed_raw_md(tmp_path: Path, slug="data_table_order_detail", body="## 订单\n\n| order_id |\n|---|\n| O1 |\n"):
    raw = tmp_path / "raw"
    md_root = tmp_path / "md"
    raw_f = raw / "data_table" / "order_detail.xlsx"
    raw_f.parent.mkdir(parents=True)
    raw_f.write_bytes(b"rawbytes")
    # md 已 clean 就绪（{slug}__{hash8}.md）
    md_path = md_root / "data_table" / f"{slug}__a3f9c1e2.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text(body, encoding="utf-8")
    return raw_f, md_path

def _fake_client_for(md_path):
    """返回一个会让 ingest_source 走 fallback 的 None client（单测不调 LLM）。"""
    return None

def test_add_ingests_and_commits_hash(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    summ = ingest_flow.run_incremental(raw_root=tmp_path / "raw", md_root=tmp_path / "md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp,
        client=None, today="2026-08-03")
    assert summ.added == 1 and summ.failed == 0
    # hash.json 提交
    data = hash_store.load_hash(hp)
    assert "data_table_order_detail" in data
    # wiki 页 + cache + log
    expected_slug = slug_from_source_identity(str(md_path))
    assert (wiki / "sources" / f"{expected_slug}.md").exists()
    assert "data_table_order_detail" in lp.read_text(encoding="utf-8")

def test_skip_unchanged(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    # 第二次：应全 skip
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.added == 0 and summ.modified == 0 and summ.skipped == 1

def test_modify_delete_then_add_no_orphan(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    # 第一次摄入
    ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    # 改 raw 内容 → 重 clean（测试里直接重写 md 模拟 clean）
    raw.write_bytes(b"changedbytes")
    md_path2 = tmp_path / "md" / "data_table" / "data_table_order_detail__deadbeef.md"
    md_path2.write_text("## 订单\n\n| order_id |\n|---|\n| O2 |\n", encoding="utf-8")
    md_path = tmp_path / "md" / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    md_path.unlink()  # clean 已用新 hash8 重写，旧 md 删除
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.modified == 1
    # 旧 source 页不残留（页名 = slug_from_source_identity(旧 md 绝对路径)）
    old_expected_slug = slug_from_source_identity(str(md_path))
    assert not (wiki / "sources" / f"{old_expected_slug}.md").exists()
    # 新 source 页在（页名 = slug_from_source_identity(新 md 绝对路径)）
    new_expected_slug = slug_from_source_identity(str(md_path2))
    assert (wiki / "sources" / f"{new_expected_slug}.md").exists()

def test_delete_purges_source(tmp_path: Path):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    # 删 raw
    raw.unlink()
    md_path = tmp_path / "md" / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.deleted == 1
    expected_slug = slug_from_source_identity(str(md_path))
    assert not (wiki / "sources" / f"{expected_slug}.md").exists()
    assert "data_table_order_detail" not in hash_store.load_hash(hp)
    assert "\"type\": \"delete\"" in lp.read_text(encoding="utf-8") or '"type":"delete"' in lp.read_text(encoding="utf-8")

def test_add_no_md_warns_not_crash(tmp_path: Path):
    raw = tmp_path / "raw"
    raw_f = raw / "data_table" / "order_detail.xlsx"
    raw_f.parent.mkdir(parents=True)
    raw_f.write_bytes(b"rawbytes")
    # md 未 clean
    md_root = tmp_path / "md"; md_root.mkdir()
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    summ = ingest_flow.run_incremental(raw_root=raw, md_root=md_root,
        wiki_root=tmp_path/"wiki", cache_path=tmp_path/"cache.json", hash_path=hp,
        log_path=lp, client=None, today="2026-08-03")
    assert summ.failed == 0  # 不是失败，是 warn
    assert summ.added == 0
    assert any("WARN" in d or "no_md" in d for d in summ.details)

def test_single_file_error_does_not_crash_batch(tmp_path: Path, monkeypatch):
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    real = ingest_flow.ingest_source
    def boom(md_path, identity, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(ingest_flow, "ingest_source", boom)
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.failed == 1
    # 失败不提交 hash
    assert "data_table_order_detail" not in hash_store.load_hash(hp)

def test_transaction_hash_last(tmp_path: Path, monkeypatch):
    """ingest_source 成功但 upsert_hash 抛异常 → 视为失败，hash 未提交。"""
    raw, md_path = _seed_raw_md(tmp_path)
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; wiki = tmp_path / "wiki"
    def boom_upsert(*a, **k):
        raise RuntimeError("hash write boom")
    monkeypatch.setattr(ingest_flow, "upsert_hash", boom_upsert)
    summ = ingest_flow.run_incremental(raw_root=tmp_path/"raw", md_root=tmp_path/"md",
        wiki_root=wiki, cache_path=cache, hash_path=hp, log_path=lp, client=None, today="2026-08-03")
    assert summ.failed == 1

# tests/test_change_detect.py
from pathlib import Path
from l1_kb.ingest.incremental import change_detect
from l1_kb.ingest.incremental import hash_store

def _make_raw(root: Path):
    (root / "data_table").mkdir(parents=True)
    f = root / "data_table" / "order_detail.xlsx"
    f.write_bytes(b"hello")
    return f

def test_slug_of():
    assert change_detect.slug_of("data_table_order_detail__a3f9c1e2") == "data_table_order_detail"
    assert change_detect.slug_of("no_hash") == "no_hash"

def test_detect_add(tmp_path: Path):
    raw = tmp_path / "raw"
    _make_raw(raw)
    hp = tmp_path / "hash.json"
    cs = change_detect.detect_changes(raw, hp)
    assert len(cs.add) == 1
    assert cs.add[0].slug == "data_table_order_detail"
    assert cs.add[0].hash.startswith("sha256:")
    assert cs.add[0].raw_rel == "data_table/order_detail.xlsx"
    assert cs.modify == [] and cs.delete == [] and cs.skip == []

def test_detect_skip_unchanged(tmp_path: Path):
    raw = tmp_path / "raw"
    f = _make_raw(raw)
    hp = tmp_path / "hash.json"
    cs1 = change_detect.detect_changes(raw, hp)
    it = cs1.add[0]
    hash_store.upsert_hash(hp, it.slug, hash=it.hash, path=it.raw_rel, ingested_at="2026-08-03")
    cs2 = change_detect.detect_changes(raw, hp)
    assert cs2.add == [] and len(cs2.skip) == 1 and cs2.skip[0].slug == it.slug

def test_detect_modify(tmp_path: Path):
    raw = tmp_path / "raw"
    f = _make_raw(raw)
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "data_table_order_detail", hash="sha256:old",
                            path="data_table/order_detail.xlsx", ingested_at="2026-08-02")
    cs = change_detect.detect_changes(raw, hp)
    assert len(cs.modify) == 1 and cs.modify[0].hash.startswith("sha256:")
    assert cs.modify[0].hash != "sha256:old"

def test_detect_delete(tmp_path: Path):
    raw = tmp_path / "raw"
    _make_raw(raw)
    hp = tmp_path / "hash.json"
    # hash.json 记录了一个 raw 里不存在的 slug
    hash_store.upsert_hash(hp, "gone_doc", hash="sha256:x", path="gone/doc.md", ingested_at="2026-08-02")
    cs = change_detect.detect_changes(raw, hp)
    assert len(cs.delete) == 1
    assert cs.delete[0].slug == "gone_doc"
    assert cs.delete[0].raw_rel == "gone/doc.md"

def test_detect_empty_raw(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    hp = tmp_path / "hash.json"
    cs = change_detect.detect_changes(raw, hp)
    assert cs.add == [] and cs.modify == [] and cs.delete == [] and cs.skip == []

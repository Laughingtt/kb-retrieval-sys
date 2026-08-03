# tests/test_hash_store.py
from pathlib import Path
from l1_kb.ingest.incremental import hash_store

def test_upsert_then_load(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "data_table_order_detail",
                            hash="sha256:a3f9c1e2", path="data_table/order_detail.xlsx",
                            ingested_at="2026-08-03")
    data = hash_store.load_hash(hp)
    assert data["data_table_order_detail"] == {
        "hash": "sha256:a3f9c1e2",
        "path": "data_table/order_detail.xlsx",
        "ingested_at": "2026-08-03",
    }

def test_remove_hash(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "a", hash="sha256:x", path="a.md", ingested_at="2026-08-03")
    hash_store.remove_hash(hp, "a")
    assert "a" not in hash_store.load_hash(hp)
    # 删不存在的键不报错
    hash_store.remove_hash(hp, "nope")

def test_load_missing_returns_empty(tmp_path: Path):
    assert hash_store.load_hash(tmp_path / "nope.json") == {}

def test_load_corrupt_returns_empty(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hp.write_text("{not json", encoding="utf-8")
    assert hash_store.load_hash(hp) == {}

def test_save_is_atomic(tmp_path: Path):
    hp = tmp_path / "hash.json"
    hash_store.upsert_hash(hp, "a", hash="sha256:x", path="a.md", ingested_at="2026-08-03")
    # 无残留 .tmp
    assert not list(tmp_path.glob("*.tmp"))
    # 中文/特殊字符 ensure_ascii=False
    hp.write_text("{}", encoding="utf-8")
    hash_store.upsert_hash(hp, "cn_测试", hash="sha256:y", path="中文/文件.xlsx", ingested_at="2026-08-03")
    assert "中文" in hp.read_text(encoding="utf-8")

# tests/test_delete.py
from pathlib import Path
from l1_kb.ingest.incremental import delete, hash_store
from l1_kb.ingest.wiki.ingest_cache import save_cache

def _seed(tmp_path: Path):
    md_root = tmp_path / "md"
    wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    # md 文件 {slug}__a3f9c1e2.md
    md_path = md_root / "data_table" / "data_table_order_detail__a3f9c1e2.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n", encoding="utf-8")
    # 两张 wiki 页
    src = wiki / "sources" / "data_table_order_detail__a3f9c1e2.md"
    ent = wiki / "entities" / "entity_order.md"
    src.parent.mkdir(parents=True)
    ent.parent.mkdir(parents=True)
    src.write_text("---\ntype: source\n---\nbody\n", encoding="utf-8")
    ent.write_text("---\ntype: entity\n---\nbody\n", encoding="utf-8")
    # cache: identity=md 绝对路径, paths=[src, ent]
    save_cache(cache, str(md_path), "somehash", [str(src), str(ent)])
    hash_store.upsert_hash(hp, "data_table_order_detail", hash="sha256:x",
                            path="data_table/order_detail.xlsx", ingested_at="2026-08-02")
    return md_path, src, ent

def test_find_md_for_slug(tmp_path: Path):
    md_root = tmp_path / "md"
    md_path, _, _ = _seed(tmp_path)
    found = delete.find_md_for_slug(md_root, "data_table_order_detail")
    assert found == md_path
    assert delete.find_md_for_slug(md_root, "nope") is None

def test_purge_deletes_pages_md_cache_hash(tmp_path: Path):
    md_root = tmp_path / "md"
    md_path, src, ent = _seed(tmp_path)
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    wiki = tmp_path / "wiki"
    res = delete.purge_source(slug="data_table_order_detail", md_root=md_root,
                              wiki_root=wiki, cache_path=cache, hash_path=hp,
                              today="2026-08-03")
    assert sorted(res.deleted_pages) == sorted([str(src), str(ent)])
    assert res.deleted_md is True
    assert not src.exists() and not ent.exists()
    assert not md_path.exists()
    # cache 条目被删
    import json
    assert str(md_path) not in json.loads(cache.read_text(encoding="utf-8"))
    # hash 条目被删
    from l1_kb.ingest.incremental.hash_store import load_hash
    assert "data_table_order_detail" not in load_hash(hp)
    # rebuild_index 后无幽灵（index.md 不列已删页）
    assert (wiki / "index.md").exists()
    assert "data_table_order_detail" not in (wiki / "index.md").read_text(encoding="utf-8")

def test_purge_no_cache_entry_still_globs_source_page(tmp_path: Path):
    """cache 无 identity（如 process paths:[]）→ glob 兜底删 source 页。"""
    md_root = tmp_path / "md"
    wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    md_path = md_root / "process" / "process_policy__2cc0e310.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## x\n", encoding="utf-8")
    src = wiki / "sources" / "process_policy__2cc0e310.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\ntype: source\n---\nbody\n", encoding="utf-8")
    # 故意不写 cache 条目
    hash_store.upsert_hash(hp, "process_policy", hash="sha256:x", path="process/policy.md", ingested_at="2026-08-02")
    res = delete.purge_source(slug="process_policy", md_root=md_root, wiki_root=wiki,
                              cache_path=cache, hash_path=hp, today="2026-08-03")
    assert res.deleted_md is True
    assert not src.exists()  # glob 兜底删了
    from l1_kb.ingest.incremental.hash_store import load_hash
    assert "process_policy" not in load_hash(hp)

def test_purge_missing_slug_is_noop(tmp_path: Path):
    md_root = tmp_path / "md"; md_root.mkdir()
    wiki = tmp_path / "wiki"; wiki.mkdir()
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    res = delete.purge_source(slug="ghost", md_root=md_root, wiki_root=wiki,
                              cache_path=cache, hash_path=hp, today="2026-08-03")
    assert res.deleted_pages == [] and res.deleted_md is False

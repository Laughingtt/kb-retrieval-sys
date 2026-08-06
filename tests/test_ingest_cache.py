from kb_retrieval.kb.ingest.wiki.ingest_cache import check_cache, save_cache, content_hash


def test_content_hash_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


def test_cache_miss_then_hit(tmp_path):
    cache = tmp_path / "ingest-cache.json"
    h = content_hash("md content")
    # 未存 → miss
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is False
    # 写入两张页
    pages = [tmp_path / "wiki" / "sources" / "a.md", tmp_path / "wiki" / "entities" / "b.md"]
    for p in pages:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    save_cache(cache, "data_table/order_detail.xlsx", h, [str(p) for p in pages])
    # 页都在 → hit
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is True


def test_cache_ghost_invalidated_when_page_deleted(tmp_path):
    cache = tmp_path / "ingest-cache.json"
    h = content_hash("md content")
    pages = [tmp_path / "wiki" / "sources" / "a.md"]
    pages[0].parent.mkdir(parents=True, exist_ok=True)
    pages[0].write_text("x", encoding="utf-8")
    save_cache(cache, "data_table/order_detail.xlsx", h, [str(p) for p in pages])
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is True
    # 删页 → 幽灵条目失效 → miss
    pages[0].unlink()
    assert check_cache(cache, "data_table/order_detail.xlsx", h) is False


def test_cache_invalidated_on_content_change(tmp_path):
    cache = tmp_path / "ingest-cache.json"
    h1 = content_hash("v1")
    save_cache(cache, "x.xlsx", h1, [])
    assert check_cache(cache, "x.xlsx", content_hash("v2")) is False

from l1_kb.retrieval.bm25 import BM25Retriever


def test_ranking_exact_term_top():
    entries = [
        {"slug": "entity_order_detail", "section_id": "s0", "title": "订单明细表", "body_text": "| order_id | string | 订单唯一标识 |"},
        {"slug": "source_other", "section_id": "s0", "title": "其他", "body_text": "本页与订单无关，无字段"},
    ]
    r = BM25Retriever(entries)
    hits = r.search("order_id", top_n=5)
    assert len(hits) >= 1
    assert hits[0].doc_id == "entity_order_detail"
    assert hits[0].source == "bm25"


def test_top_n_truncation():
    entries = [
        {"slug": f"d{i}", "section_id": "s0", "title": f"order_id {i}", "body_text": "order_id"}
        for i in range(10)
    ]
    r = BM25Retriever(entries)
    hits = r.search("order_id", top_n=3)
    assert len(hits) == 3


def test_empty_query_or_corpus():
    r = BM25Retriever([])
    assert r.search("order_id") == []
    entries = [{"slug": "a", "section_id": "s0", "title": "order_id", "body_text": "order_id"}]
    r2 = BM25Retriever(entries)
    assert r2.search("") == []

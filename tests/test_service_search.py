from pathlib import Path
from kb_retrieval.kb.service.store import load_store
from kb_retrieval.kb.service.search import search


def _wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "sources" / "order__a3f9c1e2.md").write_text(
        "---\ntype: source\ntitle: 订单表\n---\n"
        "# 订单表\n\norder_id 主键, order_amount 订单金额。\n\n"
        "## 字段说明\n\norder_amount 金额字段。\n",
        encoding="utf-8",
    )
    (w / "entities").mkdir(parents=True)
    (w / "entities" / "customer__bb.md").write_text(
        "---\ntype: entity\ntitle: 客户\n---\n"
        "# 客户\n\ncustomer_id 主键, 客户主数据。\n",
        encoding="utf-8",
    )


def test_search_hits_relevant(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    hits = search(store, "订单金额", top_k=5)
    assert len(hits) >= 1
    # 订单表相关 section 排前列
    assert hits[0].doc_id == "order__a3f9c1e2"
    assert "order_amount" in hits[0].snippet or "订单金额" in hits[0].snippet


def test_search_returns_searchhit(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path)
    hits = search(store, "客户", top_k=5)
    from kb_retrieval.kb.retrieval.base import SearchHit
    assert isinstance(hits[0], SearchHit)
    assert hits[0].doc_id == "customer__bb"


def test_search_no_match_empty(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    hits = search(store, "zzzznomatch", top_k=5)
    assert hits == []


def test_search_snippet_bounded(tmp_path):
    _wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    hits = search(store, "订单", top_k=5)
    for h in hits:
        assert len(h.snippet) <= 500

from pathlib import Path
from fastapi.testclient import TestClient


def _wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "entities").mkdir(parents=True)
    (w / "concepts").mkdir()
    (w / "processes").mkdir()
    (w / "sources" / "order__a3f9c1e2.md").write_text(
        "---\ntype: source\ntitle: 订单表\nupdated: 2026-08-04\n---\n"
        "# 订单表\n\norder_id 主键。\n\n## 字段说明\n\norder_amount 金额。\n",
        encoding="utf-8",
    )
    (w / "entities" / "customer__bb.md").write_text(
        "---\ntype: entity\ntitle: 客户\nupdated: 2026-08-04\n---\n# 客户\n\n主数据。\n",
        encoding="utf-8",
    )
    (w / "index.md").write_text(
        "# Wiki Index\n\n_updated: 2026-08-04_\n\n## source\n\n- [[order__a3f9c1e2|订单表]]\n\n"
        "## entity\n\n- [[customer__bb|客户]]\n",
        encoding="utf-8",
    )


def _client(tmp_path, monkeypatch):
    import l1_kb.config as config
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    # WIKI_ROOT 走 env，直接设
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    from l1_kb.service.app import app
    return TestClient(app)


def test_health(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["page_count"] == 2
    assert isinstance(body["wiki_root"], str)
    assert str(tmp_path / "wiki") in body["wiki_root"]
    assert body["last_updated"] == "2026-08-04"


def test_categories(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/categories")
    assert r.status_code == 200
    cats = {x["type"]: x["count"] for x in r.json()}
    # ALL 4 types present including count=0
    assert set(cats.keys()) == {"source", "entity", "concept", "process"}
    assert cats["source"] == 1
    assert cats["entity"] == 1
    assert cats["concept"] == 0
    assert cats["process"] == 0


def test_documents_list_pagination(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?page=1&page_size=50")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "page", "page_size", "total"}
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["total"] == 2
    items = body["items"]
    assert len(items) == 2
    slugs = {d["slug"] for d in items}
    assert "order__a3f9c1e2" in slugs
    # 摘要不含 body
    assert "body" not in items[0]
    # each item has section_count and updated
    for it in items:
        assert "section_count" in it
        assert "updated" in it


def test_documents_list_type_filter(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?type=entity")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["slug"] == "customer__bb"


def test_documents_illegal_type_422(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?type=bogus")
    assert r.status_code == 422


def test_documents_pagination_total(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    # page_size=1 → only 1 item in slice, but total=2
    r = c.get("/documents?page=1&page_size=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["page_size"] == 1


def test_document_detail(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents/order__a3f9c1e2")
    assert r.status_code == 200
    doc = r.json()
    assert doc["slug"] == "order__a3f9c1e2"
    assert doc["type"] == "source"
    assert "updated" in doc
    assert doc["updated"] == "2026-08-04"
    assert len(doc["sections"]) >= 1
    assert "body" in doc["sections"][0]


def test_document_detail_404(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents/nope")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]
    # 路径穿越 → 404（路由层拒绝或端点拒绝，均不泄露 FS）
    r2 = c.get("/documents/..%2Findex")
    assert r2.status_code == 404


def test_index(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/index")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "categories" not in body
    assert "updated" not in body
    entries = body["entries"]
    assert isinstance(entries, list)
    for e in entries:
        assert "type" in e and "title" in e and "slug" in e
    assert any(e["slug"] == "order__a3f9c1e2" for e in entries)


def test_index_fallback_no_index_md(tmp_path, monkeypatch):
    _wiki(tmp_path)
    (tmp_path / "wiki" / "index.md").unlink()
    c = _client(tmp_path, monkeypatch)
    r = c.get("/index")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert any(e["slug"] == "order__a3f9c1e2" for e in entries)


def test_search_ok(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/search?q=订单")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "订单"
    assert "top_k" not in body
    assert body["total"] >= 1
    assert len(body["hits"]) >= 1
    assert body["hits"][0]["doc_id"] == "order__a3f9c1e2"


def test_search_empty_q_400(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/search?q=")
    assert r.status_code == 400
    assert r.json()["detail"] == "query must not be empty"
    assert c.get("/search").status_code == 400


def test_search_no_hit_200(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/search?q=不存在的词xyz")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["hits"] == []


def test_no_write_routes(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    # 常见写方法应 405（路由不存在该方法）
    assert c.post("/search").status_code == 405
    assert c.delete("/documents/x").status_code == 405

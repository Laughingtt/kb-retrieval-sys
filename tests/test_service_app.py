import re
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
    assert r.json()["status"] == "ok"
    assert r.json()["pages"] == 2


def test_categories(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/categories")
    assert r.status_code == 200
    cats = {x["type"]: x["count"] for x in r.json()}
    assert cats.get("source") == 1
    assert cats.get("entity") == 1
    # 仅含 count>0
    assert "concept" not in cats


def test_documents_list_pagination(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?page=1&page_size=50")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 2
    slugs = {d["slug"] for d in docs}
    assert "order__a3f9c1e2" in slugs
    # 摘要不含 body
    assert "body" not in docs[0]


def test_documents_list_type_filter(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents?type=entity")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 1
    assert docs[0]["slug"] == "customer__bb"


def test_document_detail(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/documents/order__a3f9c1e2")
    assert r.status_code == 200
    doc = r.json()
    assert doc["slug"] == "order__a3f9c1e2"
    assert doc["type"] == "source"
    assert len(doc["sections"]) >= 1
    assert "body" in doc["sections"][0]


def test_document_detail_404(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    assert c.get("/documents/nope").status_code == 404
    # 路径穿越
    assert c.get("/documents/..%2Findex").status_code == 404


def test_index(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/index")
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == "2026-08-04"
    cats = {x["type"]: x["pages"] for x in body["categories"]}
    assert any(p["slug"] == "order__a3f9c1e2" for p in cats["source"])


def test_search_ok(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/search?q=订单")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "订单"
    assert len(body["hits"]) >= 1
    assert body["hits"][0]["doc_id"] == "order__a3f9c1e2"


def test_search_empty_q_400(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    assert c.get("/search?q=").status_code == 400
    assert c.get("/search").status_code == 400


def test_no_write_routes(tmp_path, monkeypatch):
    _wiki(tmp_path)
    c = _client(tmp_path, monkeypatch)
    # 常见写方法应 405（路由不存在该方法）
    assert c.post("/search").status_code == 405
    assert c.delete("/documents/x").status_code == 405

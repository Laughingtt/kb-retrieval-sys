# kb_retrieval/agent/tests/test_kb_client.py
import httpx
import pytest
from kb_retrieval.agent.kb_client import KBClient, KBClientError


def _fake_transport(routes: dict):
    """routes: { (method, path): (status, json_body) }，path 含 querystring。"""
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, str(request.url))
        # 允许 querystring 匹配：先精确，再只比 path
        if key not in routes:
            for (m, p), (st, body) in routes.items():
                if m == request.method and request.url.path == p:
                    key = (m, p)
                    break
        if key not in routes:
            return httpx.Response(404, json={"detail": "no route"})
        st, body = routes[key]
        return httpx.Response(st, json=body)
    return handler


def test_get_categories(monkeypatch):
    transport = httpx.MockTransport(_fake_transport({
        ("GET", "/categories"): (200, [{"type": "source", "count": 1}]),
    }))
    monkeypatch.setattr("kb_retrieval.agent.config.KB_BASE_URL", "http://test")
    c = KBClient(base_url="http://test", timeout=5)
    c._client = httpx.Client(transport=transport, base_url="http://test")
    assert c.get_categories() == [{"type": "source", "count": 1}]


def test_get_documents_params(monkeypatch):
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"items": [], "page": 1, "page_size": 50, "total": 0})
    monkeypatch.setattr("kb_retrieval.agent.config.KB_BASE_URL", "http://test")
    c = KBClient(base_url="http://test")
    c._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    c.get_documents(type="entity", page=2, page_size=10)
    assert "type=entity" in seen["url"]
    assert "page=2" in seen["url"]
    assert "page_size=10" in seen["url"]


def test_get_search(monkeypatch):
    monkeypatch.setattr("kb_retrieval.agent.config.KB_BASE_URL", "http://test")
    c = KBClient(base_url="http://test")
    c._client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"query": "x", "total": 0, "hits": []})),
        base_url="http://test")
    out = c.get_search("x", top_k=5)
    assert out["query"] == "x"


def test_get_document_404_raises(monkeypatch):
    monkeypatch.setattr("kb_retrieval.agent.config.KB_BASE_URL", "http://test")
    c = KBClient(base_url="http://test")
    c._client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(404, json={"detail": "document not found: nope"})),
        base_url="http://test")
    with pytest.raises(KBClientError) as ei:
        c.get_document("nope")
    assert ei.value.status == 404


def test_get_health_and_index(monkeypatch):
    monkeypatch.setattr("kb_retrieval.agent.config.KB_BASE_URL", "http://test")
    c = KBClient(base_url="http://test")
    c._client = httpx.Client(transport=httpx.MockTransport(_fake_transport({
        ("GET", "/health"): (200, {"status": "ok", "page_count": 3}),
        ("GET", "/index"): (200, {"entries": []}),
    })), base_url="http://test")
    assert c.get_health()["status"] == "ok"
    assert c.get_index() == {"entries": []}

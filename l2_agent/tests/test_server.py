# l2_agent/tests/test_server.py
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client_with_agent(agent_result):
    """构造 server，AgentLoop.run 被 patch 成返回 agent_result。

    patch 以 context-manager 形式返回，调用方需在 `with` 块内发请求，
    确保 _build_agent 在请求处理时仍被替换（避免实例化真实 AgentLoop 触发网络）。
    """
    from l2_agent.server import app
    fake = MagicMock()
    fake.run.return_value = agent_result
    patcher = patch("l2_agent.server._build_agent", return_value=fake)
    return patcher, fake, app


def test_models():
    from l2_agent.server import app
    c = TestClient(app)
    r = c.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert any(m["id"] == "kb-agent" for m in body["data"])


def test_chat_non_stream(monkeypatch):
    monkeypatch.setattr("l2_agent.config.LLM_API_KEY", "sk-test")
    patcher, fake, app = _client_with_agent({"content": "答案 [slug §s0]", "tool_calls_count": 2, "trace": []})
    with patcher:
        c = TestClient(app)
        r = c.post("/v1/chat/completions", json={
            "model": "kb-agent", "messages": [{"role": "user", "content": "问"}], "stream": False})
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "答案 [slug §s0]"
    assert body["usage"]["tool_calls_count"] == 2
    # 传给 agent 的 messages 透传
    fake.run.assert_called_once()


def test_chat_stream(monkeypatch):
    monkeypatch.setattr("l2_agent.config.LLM_API_KEY", "sk-test")
    patcher, fake, app = _client_with_agent({"content": "流式答案", "tool_calls_count": 1, "trace": []})
    # on_delta 把 content 整段吐出
    def fake_run(messages, on_delta=None):
        if on_delta:
            on_delta("流式答案")
        return {"content": "流式答案", "tool_calls_count": 1, "trace": []}
    fake.run.side_effect = fake_run
    with patcher:
        c = TestClient(app)
        r = c.post("/v1/chat/completions", json={
            "model": "kb-agent", "messages": [{"role": "user", "content": "问"}], "stream": True})
    assert r.status_code == 200
    body = "".join(r.iter_lines())
    assert "data:" in body
    assert "[DONE]" in body
    assert "流式答案" in body


def test_health(monkeypatch):
    monkeypatch.setattr("l2_agent.config.LLM_API_KEY", "sk-test")
    from l2_agent.server import app
    with patch("l2_agent.server._l1_reachable", return_value=True):
        c = TestClient(app)
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm_configured"] is True
    assert body["l1_reachable"] is True

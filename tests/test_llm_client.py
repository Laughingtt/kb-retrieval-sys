import json
from unittest.mock import MagicMock, patch

import pytest

from kb_retrieval.kb.llm import client as client_mod
from kb_retrieval.kb.llm.client import LLMClient, LLMError


def _fake_openai(return_content):
    """返回假的 OpenAI client，chat.completions.create 返回固定 content。"""
    fake = MagicMock()
    msg = MagicMock()
    msg.message.content = return_content
    choice = MagicMock()
    choice.message = msg.message
    fake.chat.completions.create.return_value = MagicMock(choices=[choice])
    return fake


def test_chat_json_parses():
    fake = _fake_openai(json.dumps({"entities": [], "summary": "ok"}))
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        result = c.chat_json("sys", "user")
        assert result == {"entities": [], "summary": "ok"}
        # 确认请求了 json_object
        kwargs = fake.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}


def test_chat_json_retries_on_bad_json():
    fake = _fake_openai("not json")
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        with pytest.raises(LLMError):
            c.chat_json("sys", "user")


def test_chat_text_returns_string():
    fake = _fake_openai("plain text output")
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        assert c.chat_text("sys", "user") == "plain text output"


def test_chat_json_retries_once_then_succeeds():
    # 第一次非法 JSON，第二次合法
    fake = MagicMock()
    msg_bad = MagicMock(); msg_bad.message.content = "bad"
    msg_good = MagicMock(); msg_good.message.content = json.dumps({"ok": True})
    choice_bad = MagicMock(); choice_bad.message = msg_bad.message
    choice_good = MagicMock(); choice_good.message = msg_good.message
    fake.chat.completions.create.side_effect = [
        MagicMock(choices=[choice_bad]),
        MagicMock(choices=[choice_good]),
    ]
    with patch.object(client_mod, "OpenAI", return_value=fake):
        c = LLMClient(base_url="http://x", api_key="k", model="m")
        assert c.chat_json("sys", "user") == {"ok": True}
        assert fake.chat.completions.create.call_count == 2

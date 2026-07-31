"""OpenAI 兼容薄封装 —— M2 设计 §3.2。

chat_json：response_format=json_object，非法 JSON 重试一次，仍失败抛 LLMError。
chat_text：纯文本出（step2 FILE block 用）。单步超时 60s，失败即降级。
无流式、无工具——纯结构化进出。
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

__all__ = ["LLMClient", "LLMError"]


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 60.0) -> None:
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model

    def chat_json(self, system: str, user: str) -> dict[str, Any]:
        """结构化 JSON 出。非法 JSON 重试一次，仍失败抛 LLMError。"""
        for attempt in range(2):
            content = self._raw_chat(system, user, temperature=0.1, response_format={"type": "json_object"})
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                if attempt == 1:
                    raise LLMError(f"LLM 返回非法 JSON: {content[:200]!r}")
        raise LLMError("unreachable")

    def chat_text(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """纯文本出（FILE block）。"""
        return self._raw_chat(system, user, temperature=0.1, max_tokens=max_tokens)

    def _raw_chat(self, system: str, user: str, **kwargs: Any) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        return resp.choices[0].message.content or ""

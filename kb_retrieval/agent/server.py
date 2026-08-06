"""L2 FastAPI —— OpenAI 兼容 /v1/chat/completions（流式 SSE）+ /v1/models + /health。"""
from __future__ import annotations

import json
import queue
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from kb_retrieval.agent import config
from kb_retrieval.agent.agent import AgentLoop
from kb_retrieval.agent.kb_client import KBClient

__all__ = ["app", "run"]

app = FastAPI(title="L2 KB Agent", version="0.1.0")


def _build_agent() -> AgentLoop:
    if not config.llm_enabled():
        raise HTTPException(status_code=503, detail="LLM_API_KEY not configured")
    return AgentLoop()


def _l1_reachable() -> bool:
    try:
        KBClient().get_health()
        return True
    except Exception:
        return False


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatRequest(BaseModel):
    model: str = "kb-agent"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None


@app.get("/health")
def health():
    return {"status": "ok", "llm_configured": config.llm_enabled(), "l1_reachable": _l1_reachable()}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "kb-agent", "object": "model"}]}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    agent = _build_agent()
    messages = [{"role": m.role, "content": m.content or ""} for m in req.messages]
    cid = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    if req.stream:
        q: "queue.Queue[str | None]" = queue.Queue()

        def on_delta(t: str) -> None:
            q.put(t)

        def gen():
            # 先发一个 role delta
            yield _sse({"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}, cid)
            result = agent.run(messages, on_delta=on_delta)  # 同步执行，on_delta 推片入队
            q.put(None)  # 结束信号
            # drain：实际 on_delta 在 run 内同步调用，run 返回时已全部入队
            while True:
                item = q.get()
                if item is None:
                    break
                yield _sse({"choices": [{"index": 0, "delta": {"content": item}, "finish_reason": None}]}, cid)
            yield _sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}, cid)
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")
    result = agent.run(messages)
    return {
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result["content"]}, "finish_reason": "stop"}],
        "usage": {"tool_calls_count": result["tool_calls_count"]},
    }


def _sse(payload: dict, cid: str) -> str:
    payload["id"] = cid
    payload["object"] = "chat.completion.chunk"
    payload["created"] = int(time.time())
    payload["model"] = "kb-agent"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def run() -> None:
    import uvicorn
    uvicorn.run("kb_retrieval.agent.server:app", host="0.0.0.0", port=8012, reload=False)

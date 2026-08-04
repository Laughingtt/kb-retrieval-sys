"""工具循环：openai SDK stream → 解析 tool_calls → 派发 → 回填 → 自评收敛。"""
from __future__ import annotations

import json
from typing import Any, Callable

from openai import OpenAI

from l2_agent import config
from l2_agent.l1_client import L1Client
from l2_agent.prompts import SYSTEM_PROMPT, FINALIZE_HINT, GAP_HINT
from l2_agent.tools import TOOLS, dispatch, extract_grade, ToolError

__all__ = ["AgentLoop"]


class AgentLoop:
    def __init__(self, llm: OpenAI | Any = None, l1: L1Client | None = None) -> None:
        self._llm = llm or OpenAI(base_url=config.LLM_BASE_URL,
                                  api_key=config.LLM_API_KEY, timeout=config.LLM_TIMEOUT)
        self._l1 = l1 or L1Client()

    def _call_llm(self, messages: list[dict]) -> dict:
        """调一次 LLM（带工具），返回聚合后的 assistant message dict。

        实际用流式聚合；测试可 monkeypatch 此方法返回脚本化 message。
        """
        stream = self._llm.chat.completions.create(
            model=config.LLM_MODEL, messages=messages, tools=TOOLS,
            temperature=config.LLM_TEMPERATURE, stream=True,
        )
        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": tc.id, "type": "function",
                                           "function": {"name": "", "arguments": ""}}
                    if tc.id:
                        tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls[idx]["function"]["arguments"] += tc.function.arguments
        msg: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
        if tool_calls:
            msg["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
        return msg

    def run(self, messages: list[dict], *, on_delta: Callable[[str], None] | None = None) -> dict:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)
        tool_calls_count = 0
        trace: list[dict] = []
        for _turn in range(config.MAX_TURNS):
            assistant = self._call_llm(msgs)
            msgs.append(assistant)
            tcs = assistant.get("tool_calls")
            if not tcs:
                # 最终答案回合：文本 delta 外吐
                if on_delta and assistant.get("content"):
                    on_delta(assistant["content"])
                return {"content": assistant.get("content", ""), "tool_calls_count": tool_calls_count, "trace": trace}
            # 派发工具
            round_results = []
            for tc in tcs:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    content = dispatch(name, args, self._l1)
                except ToolError as e:
                    content = json.dumps({"error": str(e)}, ensure_ascii=False)
                tool_calls_count += 1
                round_results.append({"name": name, "content": content})
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
                trace.append({"tool": name, "args": args})
            # 检查自评
            grade = extract_grade(round_results)
            if grade and grade.get("sufficient"):
                msgs.append({"role": "system", "content": FINALIZE_HINT})
            # else: 继续，LLM 据 missing/next_action 自主检索
        # max_turns 到顶：强制收尾
        msgs.append({"role": "system", "content": GAP_HINT})
        assistant = self._call_llm(msgs)
        if on_delta and assistant.get("content"):
            on_delta(assistant["content"])
        return {"content": assistant.get("content", ""), "tool_calls_count": tool_calls_count, "trace": trace}

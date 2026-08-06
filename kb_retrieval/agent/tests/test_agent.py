# kb_retrieval/agent/tests/test_agent.py
import json
import pytest
from unittest.mock import MagicMock, patch
from kb_retrieval.agent.agent import AgentLoop


def _mk_msg(content=None, tool_calls=None):
    """构造一个 assistant message dict（openai SDK stream 聚合后形态）。"""
    m = {"role": "assistant", "content": content or ""}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tc(id_, name, args):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_loop_converges_on_sufficient(monkeypatch):
    """回合1: grep→grade(false) → 回合2: grep→grade(true) → 回合3: 最终文本（无 tool_calls）。"""
    monkeypatch.setattr("kb_retrieval.agent.config.LLM_API_KEY", "sk-test")
    monkeypatch.setattr("kb_retrieval.agent.config.MAX_TURNS", 10)

    fake_responses = [
        # 回合1: 一个 grep + 一个 grade(false)
        _mk_msg(tool_calls=[
            _tc("c1", "grep_docs", {"q": "接口"}),
            _tc("c2", "grade_relevance", {"sufficient": False, "missing": ["数据表"], "next_action": "grep 数据表"}),
        ]),
        # 回合2: 一个 grep + 一个 grade(true)
        _mk_msg(tool_calls=[
            _tc("c3", "grep_docs", {"q": "数据表"}),
            _tc("c4", "grade_relevance", {"sufficient": True, "missing": [], "next_action": "整合"}),
        ]),
        # 回合3: 最终文本
        _mk_msg(content="最终答案 [slug §s0]"),
    ]

    kb = MagicMock()
    kb.get_search.return_value = {"query": "x", "total": 1, "hits": [
        {"doc_id": "slug", "section_id": "s0", "title": "t", "snippet": "x", "score": 0.5, "source": "bm25"}]}

    captured = []
    loop = AgentLoop(llm=MagicMock(), kb=kb)
    loop._call_llm = MagicMock(side_effect=fake_responses)

    result = loop.run([{"role": "user", "content": "问"}], on_delta=captured.append)
    assert result["content"] == "最终答案 [slug §s0]"
    assert result["tool_calls_count"] == 4  # 4 个工具调用
    # 最终文本 delta 经 on_delta 外吐
    assert "最终答案" in "".join(captured)


def test_loop_max_turns_forces_closure(monkeypatch):
    """连续 max_turns 个 grade(false) → 到顶强制收尾，标注 gap。"""
    monkeypatch.setattr("kb_retrieval.agent.config.LLM_API_KEY", "sk-test")
    monkeypatch.setattr("kb_retrieval.agent.config.MAX_TURNS", 2)

    fake_responses = [
        _mk_msg(tool_calls=[_tc("c1", "grade_relevance", {"sufficient": False, "missing": ["x"], "next_action": "grep"})]),
        _mk_msg(tool_calls=[_tc("c2", "grade_relevance", {"sufficient": False, "missing": ["x"], "next_action": "grep"})]),
        # 第3回合（强制收尾后）：最终文本
        _mk_msg(content="基于现有信息：知识库未覆盖：x"),
    ]
    kb = MagicMock()
    loop = AgentLoop(llm=MagicMock(), kb=kb)
    loop._call_llm = MagicMock(side_effect=fake_responses)
    result = loop.run([{"role": "user", "content": "问"}])
    assert "未覆盖" in result["content"]


def test_loop_no_tool_calls_immediate(monkeypatch):
    """LLM 直接给答案（无 tool_calls）→ 立即返回。"""
    monkeypatch.setattr("kb_retrieval.agent.config.LLM_API_KEY", "sk-test")
    monkeypatch.setattr("kb_retrieval.agent.config.MAX_TURNS", 10)
    loop = AgentLoop(llm=MagicMock(), kb=MagicMock())
    loop._call_llm = MagicMock(return_value=_mk_msg(content="直接答"))
    result = loop.run([{"role": "user", "content": "问"}])
    assert result["content"] == "直接答"
    assert result["tool_calls_count"] == 0

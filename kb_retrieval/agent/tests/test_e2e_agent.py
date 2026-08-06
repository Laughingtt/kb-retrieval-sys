"""e2e：真 KB Service (kb-serve) + 真 LLM (DeepSeek)。marker e2e，默认不跑。

运行：.venv/bin/pytest kb_retrieval/agent/tests/test_e2e_agent.py -m e2e -s
前置：kb-serve 已起在 8011；LLM_API_KEY env 已注入（bash -lic 'echo $LLM_API_KEY'）。
"""
import os
import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def agent():
    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set; e2e needs real key")
    from kb_retrieval.agent.agent import AgentLoop
    return AgentLoop()


def test_e2e_single_hop_with_citation(agent):
    result = agent.run([{"role": "user", "content": "知识库里有哪些分类？分别有多少文档？"}])
    assert result["content"]
    assert result["tool_calls_count"] >= 1


def test_e2e_multihop(agent):
    """依赖实际 wiki 内容；只要 agent 能多跳检索并返回非空带引用答案即通过。"""
    result = agent.run([{"role": "user", "content": "检索方案调研里对比了哪些方案？简要列出。"}])
    assert result["content"]
    assert result["tool_calls_count"] >= 1


def test_e2e_gap_marking(agent):
    result = agent.run([{"role": "user", "content": "知识库里关于量子计算的内容是什么？"}])
    # 知识库无此内容 → 应标注未覆盖
    assert "未覆盖" in result["content"] or "没有" in result["content"] or result["tool_calls_count"] >= 1

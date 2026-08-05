# l2_agent/tests/test_tools.py
import json
import pytest
from unittest.mock import MagicMock
from l2_agent.tools import TOOLS, dispatch, ToolError, extract_grade


def test_tools_schema_has_5_names():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == {"list_categories", "list_documents", "grep_docs",
                     "read_section", "grade_relevance"}


def test_grep_docs_truncates_snippet_and_caps_hits():
    l1 = MagicMock()
    l1.get_search.return_value = {
        "query": "x", "total": 20,
        "hits": [{"doc_id": f"d{i}", "section_id": "s0", "title": "t",
                  "snippet": "字" * 600, "score": 0.1, "source": "bm25"}
                 for i in range(20)],
    }
    out = json.loads(dispatch("grep_docs", {"q": "x", "top_k": 10}, l1))
    assert len(out["hits"]) <= 10
    assert all(len(h["snippet"]) <= 500 for h in out["hits"])
    # 去掉冗余 source 字段
    assert "source" not in out["hits"][0]


def test_read_section_filters_to_target():
    l1 = MagicMock()
    l1.get_document.return_value = {
        "slug": "doc1", "type": "source", "title": "T", "updated": None,
        "sections": [
            {"section_id": "s0", "title": "A", "line_start": 1, "line_end": 3, "body": "aaa"},
            {"section_id": "s1", "title": "B", "line_start": 4, "line_end": 6, "body": "bbb"},
        ],
    }
    out = json.loads(dispatch("read_section", {"slug": "doc1", "section_id": "s1"}, l1))
    assert out == {"slug": "doc1", "section_id": "s1", "title": "B", "body": "bbb"}


def test_read_section_missing_section_raises():
    l1 = MagicMock()
    l1.get_document.return_value = {"slug": "doc1", "type": "source", "title": "T",
                                    "updated": None, "sections": [
            {"section_id": "s0", "title": "A", "line_start": 1, "line_end": 3, "body": "aaa"}]}
    with pytest.raises(ToolError):
        dispatch("read_section", {"slug": "doc1", "section_id": "s9"}, l1)


def test_grade_relevance_local_no_l1_call():
    l1 = MagicMock()
    args = {"sufficient": True, "missing": [], "next_action": "整合"}
    out = json.loads(dispatch("grade_relevance", args, l1))
    assert out == args
    l1.get_search.assert_not_called()  # 确认没调 L1


def test_extract_grade_finds_grade():
    results = [
        {"name": "grep_docs", "content": '{"total":0}'},
        {"name": "grade_relevance", "content": '{"sufficient":false,"missing":["x"],"next_action":"grep x"}'},
    ]
    g = extract_grade(results)
    assert g is not None
    assert g["sufficient"] is False
    assert g["missing"] == ["x"]


def test_extract_grade_none_when_no_grade():
    assert extract_grade([{"name": "grep_docs", "content": "{}"}]) is None


def test_dispatch_unknown_tool_raises():
    with pytest.raises(ToolError):
        dispatch("nope", {}, MagicMock())


def test_dispatch_missing_required_arg_raises():
    # grep_docs 必须有 q
    with pytest.raises(ToolError):
        dispatch("grep_docs", {}, MagicMock())

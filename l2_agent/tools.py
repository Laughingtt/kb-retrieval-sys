# l2_agent/tools.py
"""5 工具：OpenAI function-calling schema + dispatch 执行函数。

前 4 个薄封装 L1Client（只读 GET）；grade_relevance 本地无 L1 调用。
回填给 LLM 的是精简 JSON（控制多跳上下文膨胀）。
"""
from __future__ import annotations

import json
from typing import Any

from l2_agent.l1_client import L1Client, L1Error

__all__ = ["TOOLS", "ToolError", "dispatch", "extract_grade"]

_SNIPPET_MAX = 500
_HITS_CAP = 10

TOOLS: list[dict] = [
    {"type": "function", "function": {
        "name": "list_categories",
        "description": "列出知识库的所有分类及其文档数，用于定位检索范围。",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_documents",
        "description": "列出某分类下的文档清单（分页），用于缩小候选范围。",
        "parameters": {"type": "object", "properties": {
            "type": {"type": "string", "enum": ["source", "entity", "concept", "process"]},
            "page": {"type": "integer", "default": 1},
            "page_size": {"type": "integer", "default": 50}}, "required": []}}},
    {"type": "function", "function": {
        "name": "grep_docs",
        "description": "用 BM25 在知识库全文精确召回片段，返回命中 section 的 snippet+score+来源。",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string", "description": "检索查询词"},
            "top_k": {"type": "integer", "default": 10}}, "required": ["q"]}}},
    {"type": "function", "function": {
        "name": "read_section",
        "description": "加载某文档某 section 的原文 body，用于精确读取已召回的内容。",
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "section_id": {"type": "string", "description": "如 s0/s1"}}, "required": ["slug", "section_id"]}}},
    {"type": "function", "function": {
        "name": "grade_relevance",
        "description": "自评当前已检索信息是否充分回答用户问题。每个检索回合后调用。",
        "parameters": {"type": "object", "properties": {
            "sufficient": {"type": "boolean"},
            "missing": {"type": "array", "items": {"type": "string"}},
            "next_action": {"type": "string"}}, "required": ["sufficient", "missing", "next_action"]}}},
]


class ToolError(Exception):
    pass


def _require(args: dict, key: str) -> Any:
    if key not in args:
        raise ToolError(f"missing required arg: {key}")
    return args[key]


def _t_list_categories(l1: L1Client, args: dict) -> Any:
    return l1.get_categories()


def _t_list_documents(l1: L1Client, args: dict) -> Any:
    return l1.get_documents(type=args.get("type"), page=args.get("page", 1),
                            page_size=args.get("page_size", 50))


def _t_grep_docs(l1: L1Client, args: dict) -> Any:
    res = l1.get_search(_require(args, "q"), top_k=args.get("top_k", 10))
    hits = []
    for h in res.get("hits", [])[:_HITS_CAP]:
        snip = h.get("snippet", "")
        if len(snip) > _SNIPPET_MAX:
            snip = snip[:_SNIPPET_MAX]
        hits.append({"doc_id": h["doc_id"], "section_id": h["section_id"],
                     "title": h["title"], "snippet": snip, "score": h["score"]})
    return {"query": res.get("query"), "total": res.get("total", 0), "hits": hits}


def _t_read_section(l1: L1Client, args: dict) -> Any:
    slug = _require(args, "slug")
    sid = _require(args, "section_id")
    doc = l1.get_document(slug)
    for s in doc.get("sections", []):
        if s["section_id"] == sid:
            return {"slug": slug, "section_id": sid, "title": s["title"], "body": s["body"]}
    raise ToolError(f"section {sid} not found in {slug}")


def _t_grade_relevance(l1: L1Client, args: dict) -> Any:
    # 本地：不调 L1。原样返回 LLM 产出的结构化判定。
    return {"sufficient": bool(_require(args, "sufficient")),
            "missing": args.get("missing", []),
            "next_action": args.get("next_action", "")}


_DISPATCH = {
    "list_categories": _t_list_categories,
    "list_documents": _t_list_documents,
    "grep_docs": _t_grep_docs,
    "read_section": _t_read_section,
    "grade_relevance": _t_grade_relevance,
}


def dispatch(name: str, args: dict, l1: L1Client) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        raise ToolError(f"unknown tool: {name}")
    try:
        result = fn(l1, args)
    except L1Error as e:
        # L1 错误塞回给 LLM 作为 tool result（Agent 自主决定重试/告知用户）
        return json.dumps({"error": f"L1 {e.status}: {e.detail}"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def extract_grade(tool_results: list[dict]) -> dict | None:
    """tool_results: [{name, content}]，返回 grade_relevance 的判定或 None。"""
    for r in tool_results:
        if r.get("name") == "grade_relevance":
            try:
                return json.loads(r["content"])
            except (json.JSONDecodeError, KeyError):
                return None
    return None

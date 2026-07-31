from l1_kb.ingest.wiki.merge import merge_page


def _page(type_, title, sources, body, created="2026-07-01", updated="2026-07-01"):
    # sources: list[str] of raw identities → YAML inline array [a, b]
    sources_yaml = "[" + ", ".join(sources) + "]"
    return (
        "---\n"
        f"type: {type_}\n"
        f'title: "{title}"\n'
        f"created: {created}\n"
        f"updated: {updated}\n"
        "tags: []\n"
        "related: []\n"
        f"sources: {sources_yaml}\n"
        "---\n\n"
        f"{body}\n"
    )


def test_new_page_written():
    new = _page("source", "T", ["data_table/order_detail.xlsx"], "body A")
    out = merge_page(None, "wiki/sources/a.md", new, "data_table/order_detail.xlsx", "2026-07-31", exists=False)
    assert out is not None
    assert "body A" in out
    assert "created: 2026-07-31" in out  # 新页 created=今日


def test_single_source_replace_body():
    existing = _page("source", "T", ["data_table/order_detail.xlsx"], "old body", updated="2026-07-01")
    new = _page("source", "T", ["data_table/order_detail.xlsx"], "new body", updated="2026-07-31")
    out = merge_page(existing, "wiki/sources/a.md", new, "data_table/order_detail.xlsx", "2026-07-31", exists=True)
    assert "new body" in out
    assert "old body" not in out  # 单源页替换 body
    assert "created: 2026-07-01" in out  # locked created 不变


def test_multi_source_append_body():
    existing = _page("entity", "E", ["data_table/order_detail.xlsx"], "orig body", updated="2026-07-01")
    new = _page("entity", "E", ["data_table/wide_table.xlsx"], "added body", updated="2026-07-31")
    out = merge_page(existing, "wiki/entities/e.md", new, "data_table/wide_table.xlsx", "2026-07-31", exists=True)
    assert "orig body" in out
    assert "added body" in out
    assert "来源补充: data_table/wide_table.xlsx" in out
    # sources 并集
    assert "data_table/order_detail.xlsx" in out
    assert "data_table/wide_table.xlsx" in out


def test_routing_mismatch_returns_none():
    new = _page("entity", "E", ["x.xlsx"], "body")
    out = merge_page(None, "wiki/sources/e.md", new, "x.xlsx", "2026-07-31", exists=False)
    assert out is None  # entity 页落在 sources 目录 → routing 不一致


def test_multi_source_dedup_when_new_body_contained():
    existing = _page("entity", "E", ["s1.xlsx"], "shared content", updated="2026-07-01")
    new = _page("entity", "E", ["s2.xlsx"], "shared content", updated="2026-07-31")
    out = merge_page(existing, "wiki/entities/e.md", new, "s2.xlsx", "2026-07-31", exists=True)
    # new_body 完全被 existing 包含 → 不重复追加段落
    assert out.count("shared content") == 1
    assert "来源补充: s2.xlsx" not in out

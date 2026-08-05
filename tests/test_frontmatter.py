from l1_kb.ingest.wiki import frontmatter as fm


def test_parse_and_dump_roundtrip():
    content = (
        "---\n"
        "type: source\n"
        'title: "订单明细表"\n'
        "created: 2026-07-31\n"
        "updated: 2026-07-31\n"
        "tags: [订单, 数据表]\n"
        "related: [entity_order_detail]\n"
        "sources: [data_table/order_detail.xlsx]\n"
        "---\n\n"
        "## 字段\n\n正文。\n"
    )
    meta, body = fm.parse(content)
    assert meta.type == "source"
    assert meta.title == "订单明细表"
    assert meta.tags == ["订单", "数据表"]
    assert meta.related == ["entity_order_detail"]
    assert meta.sources == ["data_table/order_detail.xlsx"]
    assert body.startswith("## 字段")

    dumped = fm.dump(meta)
    assert "type: source" in dumped
    assert "tags: [订单, 数据表]" in dumped


def test_parse_no_frontmatter():
    meta, body = fm.parse("纯正文无 frontmatter")
    assert meta.type == ""  # 空 frontmatter
    assert body == "纯正文无 frontmatter"


def test_parse_bare_frontmatter_without_leading_dashes():
    """LLM 漏写首行 ---：content 以 key:value 开头、随后有独立 --- 闭合。
    parse 应兜底识别为 frontmatter，避免写出双层 frontmatter 坏页。"""
    content = (
        "type: concept\n"
        'title: "RRF 融合"\n'
        "created: 2026-08-04\n"
        "updated: 2026-08-04\n"
        "tags: [检索, 融合]\n"
        "related: [entity_llm_wiki]\n"
        "sources: [docs/x.md]\n"
        "---\n\n"
        "# RRF 融合\n\n正文。\n"
    )
    meta, body = fm.parse(content)
    assert meta.type == "concept"
    assert meta.title == "RRF 融合"
    assert meta.tags == ["检索", "融合"]
    assert meta.related == ["entity_llm_wiki"]
    assert meta.sources == ["docs/x.md"]
    assert body.startswith("# RRF 融合")


def test_parse_plain_text_not_misdetected_as_frontmatter():
    """纯正文（无 --- 闭合、不像 key:value）不应被兜底误判为 frontmatter。"""
    plain = "这是一段纯正文，没有 frontmatter，也没有 --- 闭合行"
    meta, body = fm.parse(plain)
    assert meta.type == ""
    assert body == plain


def test_union_arrays():
    a = fm.Frontmatter(
        type="entity", title="A", created="2026-07-01", updated="2026-07-01",
        tags=["订单", "支付"], related=["e1"], sources=["s1.xlsx"],
    )
    b = fm.Frontmatter(
        type="entity", title="A", created="2026-07-01", updated="2026-07-31",
        tags=["支付", "退款"], related=["e2"], sources=["s2.xlsx"],
    )
    merged = fm.union_arrays(a, b)
    assert merged.tags == ["订单", "支付", "退款"]
    assert merged.related == ["e1", "e2"]
    assert merged.sources == ["s1.xlsx", "s2.xlsx"]
    # locked 字段回填旧值
    assert merged.type == "entity"
    assert merged.title == "A"
    assert merged.created == "2026-07-01"


def test_stamp_dates_new():
    m = fm.Frontmatter(type="source", title="T", created="", updated="",
                       tags=[], related=[], sources=["x.xlsx"])
    out = fm.stamp_dates(m, "2026-07-31", is_new=True)
    assert out.created == "2026-07-31"
    assert out.updated == "2026-07-31"


def test_stamp_dates_existing():
    m = fm.Frontmatter(type="source", title="T", created="2026-07-01", updated="",
                       tags=[], related=[], sources=["x.xlsx"])
    out = fm.stamp_dates(m, "2026-07-31", is_new=False)
    assert out.created == "2026-07-01"  # created 不变
    assert out.updated == "2026-07-31"


def test_from_dict_null_values_coerce_to_empty():
    """YAML 空值解析为 None，from_dict 应统一归一为 '' 而非字面量 'None'。"""
    # 模拟 yaml.safe_load 把空 type:/title:/created:/updated: 行解析为 None
    meta = fm.Frontmatter.from_dict({"type": None, "title": None, "created": None, "updated": None})
    assert meta.type == ""
    assert meta.title == ""
    assert meta.created == ""
    assert meta.updated == ""
    # 显式断言不为 "None"
    assert meta.type != "None"


def test_canonicalize_sources_injects_identity():
    m = fm.Frontmatter(type="source", title="T", created="2026-07-31", updated="2026-07-31",
                       tags=[], related=[], sources=["other.xlsx"])
    out = fm.canonicalize_sources(m, "data_table/order_detail.xlsx")
    assert "data_table/order_detail.xlsx" in out.sources
    # 非法引用（对路径/..）被剔除
    assert all(not s.startswith("/") and ".." not in s for s in out.sources)

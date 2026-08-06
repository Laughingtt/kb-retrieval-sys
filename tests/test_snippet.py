from kb_retrieval.kb.retrieval.snippet import make_snippet


def test_slice_lines():
    md = "line0\nline1\norder_id 字段\nline3\n"
    out = make_snippet(md, 2, 3)
    assert "order_id" in out
    assert out.startswith("line1")


def test_truncation():
    md = "\n".join("x" * 100 for _ in range(20))
    out = make_snippet(md, 1, 20, max_chars=50)
    assert len(out) <= 50


def test_out_of_range_safe():
    md = "only one line\n"
    assert make_snippet(md, 1, 999).startswith("only one line")

from kb_retrieval.kb.retrieval.base import RRFFuser, SearchHit


def _hit(doc_id, sec, score, source="bm25"):
    return SearchHit(doc_id=doc_id, section_id=sec, title="t", snippet="", score=score, source=source)


def test_single_lane_passthrough():
    bm25 = [_hit("a", "s0", 3.0), _hit("a", "s1", 2.0), _hit("b", "s0", 1.0)]
    out = RRFFuser().fuse([bm25], k=60, top_k=10)
    assert len(out) == 3
    # 单路 RRF：1/(60+rank)，rank 从 1 起
    assert out[0].doc_id == "a" and out[0].section_id == "s0"
    assert abs(out[0].score - 1 / 61) < 1e-9


def test_dedup_same_doc_section_across_lanes():
    lane1 = [_hit("a", "s0", 5.0)]
    lane2 = [_hit("a", "s0", 4.0), _hit("b", "s0", 1.0)]
    out = RRFFuser().fuse([lane1, lane2], k=60, top_k=10)
    # (a,s0) 两路融合：1/61 + 1/61
    a_hits = [h for h in out if h.doc_id == "a" and h.section_id == "s0"]
    assert len(a_hits) == 1
    assert abs(a_hits[0].score - 2 / 61) < 1e-9
    assert len(out) == 2


def test_top_k_truncation():
    bm25 = [_hit(f"d{i}", "s0", float(10 - i)) for i in range(20)]
    out = RRFFuser().fuse([bm25], k=60, top_k=5)
    assert len(out) == 5


def test_empty_input():
    assert RRFFuser().fuse([], k=60, top_k=10) == []
    assert RRFFuser().fuse([[]], k=60, top_k=10) == []

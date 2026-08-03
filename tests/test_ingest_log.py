# tests/test_ingest_log.py
from pathlib import Path
from l1_kb.ingest.incremental import ingest_log

def test_append_ingest_add(tmp_path: Path):
    lp = tmp_path / "ingest_log.jsonl"
    ingest_log.append_ingest(lp, today="2026-08-03", doc_id="dt_order__a3f9c1e2",
                              action="add", source="data_table/order_detail.xlsx")
    lines = ingest_log.read_log(lp)
    assert len(lines) == 1
    assert lines[0] == {
        "ts": "2026-08-03", "type": "ingest",
        "doc_id": "dt_order__a3f9c1e2", "action": "add",
        "source": "data_table/order_detail.xlsx",
    }

def test_append_delete_and_lint_and_rebuild(tmp_path: Path):
    lp = tmp_path / "ingest_log.jsonl"
    ingest_log.append_delete(lp, today="2026-08-03", doc_id="dt_order__a3f9c1e2",
                              source="data_table/order_detail.xlsx")
    ingest_log.append_lint(lp, today="2026-08-03", issues=5, errors=1, warnings=3, info=1)
    ingest_log.append_rebuild(lp, today="2026-08-03")
    lines = ingest_log.read_log(lp)
    assert [l["type"] for l in lines] == ["delete", "lint", "rebuild"]
    assert lines[1] == {"ts": "2026-08-03", "type": "lint",
                        "issues": 5, "errors": 1, "warnings": 3, "info": 1}
    assert lines[2] == {"ts": "2026-08-03", "type": "rebuild"}

def test_read_log_skips_bad_lines(tmp_path: Path):
    lp = tmp_path / "ingest_log.jsonl"
    lp.write_text('{"ts":"2026-08-03","type":"rebuild"}\n{bad json}\n', encoding="utf-8")
    lines = ingest_log.read_log(lp)
    assert len(lines) == 1

def test_read_log_missing(tmp_path: Path):
    assert ingest_log.read_log(tmp_path / "nope.jsonl") == []

def test_append_creates_parent(tmp_path: Path):
    lp = tmp_path / "sub" / "ingest_log.jsonl"
    ingest_log.append_rebuild(lp, today="2026-08-03")
    assert lp.exists()

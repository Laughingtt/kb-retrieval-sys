# tests/test_lint.py
import json
from pathlib import Path
from kb_retrieval.kb.ingest.lint import checker
from kb_retrieval.kb.ingest.wiki.index_log import rebuild_index
from kb_retrieval.kb.ingest.incremental import hash_store, ingest_log

def _seed_clean_wiki(tmp_path: Path):
    wiki = tmp_path / "wiki"
    hp = tmp_path / "hash.json"
    lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"
    md_root = tmp_path / "md"; md_root.mkdir()
    rebuild_index(wiki, "2026-08-03")
    (wiki / "log.md").write_text("# Wiki Log\n", encoding="utf-8")
    hash_store.upsert_hash(hp, "x", hash="sha256:x", path="x.md", ingested_at="2026-08-03")
    cache.write_text("{}", encoding="utf-8")
    return wiki, hp, lp, cache, md_root

def test_lint_clean_wiki_no_issues(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert rep.errors == 0

def test_l1_format_bad_index(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    (wiki / "index.md").write_text("wrong first line\n", encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L1_FORMAT" and i.level == "error" for i in rep.issues)

def test_l1_bad_ingest_log_line(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    lp.write_text('{"ts":"2026-08-03","type":"rebuild"}\n{bad}\n', encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L1_FORMAT" for i in rep.issues)

def test_l2_ghost_reference(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    # index 列了 ghost 页，但磁盘没有
    idx = wiki / "index.md"
    idx.write_text("# Wiki Index\n_updated: 2026-08-03_\n\n## source\n- [[ghost_page|Ghost]]\n", encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L2_GHOST" and i.level == "error" and i.page == "ghost_page" for i in rep.issues)

def test_l2_missing_from_index(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    src = wiki / "sources" / "entity_foo.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\ntype: source\ntitle: \"foo\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: []\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-03")  # 让 index 含它
    # 手动从 index 删掉它模拟漏列
    idx = wiki / "index.md"
    idx.write_text("# Wiki Index\n_updated: 2026-08-03_\n\n_(暂无页面)_\n", encoding="utf-8")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L2_MISSING" and i.level == "warn" for i in rep.issues)

def test_l3_orphan(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    ent = wiki / "entities" / "entity_lonely.md"
    ent.parent.mkdir(parents=True)
    ent.write_text("---\ntype: entity\ntitle: \"lonely\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: []\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L3_ORPHAN" and i.page == "entity_lonely" for i in rep.issues)

def test_l4_missing_crossref(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    e1 = wiki / "entities" / "entity_a.md"
    e2 = wiki / "entities" / "entity_b.md"
    e1.parent.mkdir(parents=True)
    # 共享 tags，但 related 互不指向 → L4
    e1.write_text("---\ntype: entity\ntitle: \"a\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: [order, api]\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    e2.write_text("---\ntype: entity\ntitle: \"b\"\ncreated: 2026-08-03\nupdated: 2026-08-03\ntags: [order, api]\nrelated: []\nsources: []\n---\nbody\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L4_XREF" for i in rep.issues)

def test_l5_data_gap(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    # 没有任何 source 页
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    assert any(i.code == "L5_GAP" and i.level == "info" for i in rep.issues)

def test_report_counts(tmp_path: Path):
    wiki, hp, lp, cache, md_root = _seed_clean_wiki(tmp_path)
    rebuild_index(wiki, "2026-08-03")
    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-03")
    total_issues = len(rep.issues)
    assert rep.errors + rep.warnings + rep.info == total_issues
    assert rep.ts == "2026-08-03"

def test_lint_report_write_and_summary(tmp_path):
    from kb_retrieval.kb.ingest.lint.report import write_report, format_summary, exit_code
    from kb_retrieval.kb.ingest.lint.checker import Issue, LintReport
    rep = LintReport(ts="2026-08-03", issues=[
        Issue("L2_GHOST", "error", "幽灵", page="entity_foo"),
        Issue("L3_ORPHAN", "warn", "孤儿", page="concept_bar"),
        Issue("L5_GAP", "info", "缺口", type="process"),
    ])
    rep.errors = 1; rep.warnings = 1; rep.info = 1
    out = tmp_path / "lint_report.json"
    write_report(rep, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["errors"] == 1 and data["warnings"] == 1 and data["info"] == 1
    assert len(data["issues"]) == 3
    assert data["issues"][0]["code"] == "L2_GHOST"
    s = format_summary(rep)
    assert "errors: 1" in s and "warnings: 1" in s and "L2_GHOST" in s
    assert exit_code(rep) == 1
    rep.errors = 0
    assert exit_code(rep) == 0

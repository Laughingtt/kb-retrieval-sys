from l1_kb.ingest.wiki import index_log


def _write(p, content):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_rebuild_index_groups_by_type_sorted(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki / "entities" / "b_entity.md",
           "---\ntype: entity\ntitle: \"B\"\ncreated: 2026-07-01\nupdated: 2026-07-01\ntags: []\nrelated: []\nsources: [x]\n---\n\nbody\n")
    _write(wiki / "entities" / "a_entity.md",
           "---\ntype: entity\ntitle: \"A\"\ncreated: 2026-07-01\nupdated: 2026-07-01\ntags: []\nrelated: []\nsources: [x]\n---\n\nbody\n")
    _write(wiki / "sources" / "src1.md",
           "---\ntype: source\ntitle: \"Src1\"\ncreated: 2026-07-01\nupdated: 2026-07-01\ntags: []\nrelated: []\nsources: [x]\n---\n\nbody\n")
    # index.md / log.md 应被排除
    _write(wiki / "index.md", "# old index\n")
    _write(wiki / "log.md", "# Wiki Log\n")

    index_log.rebuild_index(wiki, "2026-07-31")
    idx = (wiki / "index.md").read_text(encoding="utf-8")
    assert idx.startswith("# Wiki Index")
    # 按 type 分组（段标题用 label），组内按 title 排序
    assert idx.index("## 原件摘要") < idx.index("## 业务实体")
    assert idx.index("[[a_entity|A]]") < idx.index("[[b_entity|B]]")
    # index/log 茎被排除
    assert "index.md" not in idx.replace("# Wiki Index", "")


def test_rebuild_index_empty(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    index_log.rebuild_index(wiki, "2026-07-31")
    assert (wiki / "index.md").read_text(encoding="utf-8").startswith("# Wiki Index")


def test_append_log(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    index_log.append_log(wiki, "data_table/order_detail.xlsx", "2026-07-31")
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert log.startswith("# Wiki Log")
    assert "## [2026-07-31] ingest | data_table/order_detail.xlsx" in log
    # 再次追加不重复首行
    index_log.append_log(wiki, "process/policy.md", "2026-07-31")
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert log.count("# Wiki Log") == 1
    assert "## [2026-07-31] ingest | process/policy.md" in log

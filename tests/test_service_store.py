from pathlib import Path
from l1_kb.service.store import load_store, PageEntry, SectionEntry, WikiStore


def _make_wiki(root: Path) -> None:
    w = root / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "entities").mkdir()
    (w / "concepts").mkdir()
    (w / "processes").mkdir()
    (w / "sources" / "order_detail__a3f9c1e2.md").write_text(
        "---\n"
        "type: source\n"
        "title: 订单明细表\n"
        "updated: 2026-08-04\n"
        "---\n"
        "# 订单明细表\n\n"
        "字段 order_id 为主键。\n\n"
        "## 字段说明\n\n"
        "order_amount 订单金额。\n",
        encoding="utf-8",
    )
    (w / "entities" / "customer__bb.md").write_text(
        "---\ntype: entity\ntitle: 客户\nupdated: 2026-08-04\n---\n"
        "# 客户\n\n客户主数据。\n",
        encoding="utf-8",
    )
    # index/log/overview 应被跳过
    (w / "index.md").write_text("# Wiki Index\n", encoding="utf-8")
    (w / "log.md").write_text("# Wiki Log\n", encoding="utf-8")


def test_load_store_parses_pages(tmp_path):
    _make_wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    assert isinstance(store, WikiStore)
    slugs = {p.slug for p in store.pages}
    assert "order_detail__a3f9c1e2" in slugs
    assert "customer__bb" in slugs
    assert "index" not in slugs  # 跳过 index
    assert "log" not in slugs    # 跳过 log


def test_load_store_by_slug_and_type(tmp_path):
    _make_wiki(tmp_path)
    store = load_store(tmp_path / "wiki")
    page = store.by_slug["order_detail__a3f9c1e2"]
    assert page.type == "source"
    assert page.title == "订单明细表"
    assert len(page.sections) >= 1
    assert isinstance(page.sections[0], SectionEntry)
    # by_type 分组
    assert {p.slug for p in store.by_type["source"]} == {"order_detail__a3f9c1e2"}
    assert {p.slug for p in store.by_type["entity"]} == {"customer__bb"}


def test_load_store_section_body_truncated(tmp_path):
    root = tmp_path / "wiki"
    (root / "sources").mkdir(parents=True)
    body = "# T\n\n" + ("x" * 3000) + "\n"
    (root / "sources" / "big__c1.md").write_text(
        "---\ntype: source\ntitle: big\n---\n" + body, encoding="utf-8"
    )
    store = load_store(root)
    page = store.by_slug["big__c1"]
    # section body 截断到 ≤2000 + 截断标记
    assert any(len(s.body) <= 2000 + len("…[截断]") for s in page.sections)


def test_load_store_empty_wiki(tmp_path):
    store = load_store(tmp_path / "nope")
    assert store.pages == []
    assert store.by_slug == {}

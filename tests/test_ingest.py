from pathlib import Path
from unittest.mock import MagicMock

from kb_retrieval.kb.ingest.wiki import ingest


def _fake_client(step1_json, step2_text):
    c = MagicMock()
    c.chat_json.return_value = step1_json
    c.chat_text.return_value = step2_text
    return c


def test_ingest_writes_source_and_entity_pages(tmp_path):
    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n\n| order_id | customer |\n|---|---|\n| O1 | 张三 |\n", encoding="utf-8")

    step1 = {
        "entities": [{"name": "订单明细表", "slug": "entity_order_detail", "role": "数据表", "exists": False}],
        "concepts": [], "processes": [],
        "summary": "订单与订单明细两表。",
        "keywords": ["order_id", "customer"],
    }
    step2 = (
        "---FILE: wiki/sources/data_table_order_detail.md---\n"
        "---\ntype: source\ntitle: \"order_detail\"\ncreated: 2026-07-31\nupdated: 2026-07-31\ntags: []\nrelated: []\nsources: [data_table/order_detail.xlsx]\n---\n\n## 字段\n\n| order_id | customer |\n---END FILE---\n"
        "---FILE: wiki/entities/entity_order_detail.md---\n"
        "---\ntype: entity\ntitle: \"订单明细表\"\ncreated: 2026-07-31\nupdated: 2026-07-31\ntags: []\nrelated: []\nsources: [data_table/order_detail.xlsx]\n---\n\n订单明细表实体。\n---END FILE---\n"
    )
    client = _fake_client(step1, step2)
    res = ingest.ingest_source(
        md_path, "data_table/order_detail.xlsx",
        wiki_root=wiki, cache_path=tmp_path / "cache.json",
        client=client, today="2026-07-31", index_md="# Wiki Index\n",
    )
    assert res.fallback is False
    assert (wiki / "sources" / "data_table_order_detail.md").exists()
    assert (wiki / "entities" / "entity_order_detail.md").exists()
    assert (wiki / "index.md").exists()
    assert (wiki / "log.md").exists()
    assert "data_table/order_detail.xlsx" in (wiki / "log.md").read_text(encoding="utf-8")


def test_ingest_cache_skips_second_run(tmp_path):
    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n|order_id|\n", encoding="utf-8")
    step1 = {"entities": [], "concepts": [], "processes": [], "summary": "s", "keywords": ["order_id"]}
    step2 = (
        "---FILE: wiki/sources/data_table_order_detail.md---\n"
        "---\ntype: source\ntitle: \"t\"\ncreated: 2026-07-31\nupdated: 2026-07-31\ntags: []\nrelated: []\nsources: [data_table/order_detail.xlsx]\n---\n\nbody\n---END FILE---\n"
    )
    client = _fake_client(step1, step2)
    cache = tmp_path / "cache.json"
    ingest.ingest_source(md_path, "data_table/order_detail.xlsx", wiki_root=wiki, cache_path=cache, client=client, today="2026-07-31", index_md="")
    # 第二次：client 不应再被调用
    client.chat_json.reset_mock()
    client.chat_text.reset_mock()
    res = ingest.ingest_source(md_path, "data_table/order_detail.xlsx", wiki_root=wiki, cache_path=cache, client=client, today="2026-07-31", index_md="")
    assert res.skipped_cached is True
    client.chat_json.assert_not_called()
    client.chat_text.assert_not_called()


def test_ingest_fallback_when_no_client(tmp_path):
    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n\n正文段落含 order_id。\n", encoding="utf-8")
    res = ingest.ingest_source(
        md_path, "data_table/order_detail.xlsx",
        wiki_root=wiki, cache_path=tmp_path / "cache.json",
        client=None, today="2026-07-31", index_md="",
    )
    assert res.fallback is True
    # fallback 仅产 source 摘要页
    assert (wiki / "sources" / "data_table_order_detail.md").exists()
    assert not (wiki / "entities").exists() or not any((wiki / "entities").iterdir())
    body = (wiki / "sources" / "data_table_order_detail.md").read_text(encoding="utf-8")
    assert "order_id" in body


def test_ingest_fallback_when_llm_error(tmp_path):
    from kb_retrieval.kb.llm.client import LLMError

    wiki = tmp_path / "wiki"
    md_path = tmp_path / "md" / "data_table" / "order_detail.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("## 订单\n\norder_id 字段。\n", encoding="utf-8")
    client = MagicMock()
    client.chat_json.side_effect = LLMError("boom")
    res = ingest.ingest_source(
        md_path, "data_table/order_detail.xlsx",
        wiki_root=wiki, cache_path=tmp_path / "cache.json",
        client=client, today="2026-07-31", index_md="",
    )
    assert res.fallback is True
    assert (wiki / "sources" / "data_table_order_detail.md").exists()


def test_merge_page_backfills_empty_type_from_dir(tmp_path):
    from kb_retrieval.kb.ingest.wiki.merge import merge_page
    from kb_retrieval.kb.ingest.wiki.frontmatter import Frontmatter, dump

    wiki = tmp_path / "wiki"
    (wiki / "sources").mkdir(parents=True)
    fm = Frontmatter(type="", title="策略", created="2026-08-01", updated="",
                     tags=[], related=[], sources=[])
    body = "# 策略\n正文"
    new_content = dump(fm) + "\n\n" + body + "\n"
    new_path = "wiki/sources/process_policy.md"
    out = merge_page(None, new_path, new_content, "process/policy.md", "2026-08-01", exists=False)
    # 空 type 被路径反推为 source → routing 通过 → 返回整页文本（非 None）
    assert out is not None
    assert "type: source" in out or "type:source" in out.replace(" ", "")

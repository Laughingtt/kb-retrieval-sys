import pytest

from l1_kb.ingest.wiki import page_types as pt


def test_four_page_types():
    assert pt.PAGE_TYPES == frozenset({"source", "entity", "concept", "process"})


def test_dir_type_mapping_roundtrip():
    assert pt.dir_for_type("source") == "sources"
    assert pt.dir_for_type("entity") == "entities"
    assert pt.dir_for_type("concept") == "concepts"
    assert pt.dir_for_type("process") == "process"
    assert pt.type_for_dir("sources") == "source"
    assert pt.type_for_dir("process") == "process"
    assert pt.type_for_dir("unknown") is None


def test_is_valid_type():
    assert pt.is_valid_type("source") is True
    assert pt.is_valid_type("overview") is False
    assert pt.is_valid_type("") is False


def test_validate_routing_ok():
    assert pt.validate_routing("wiki/sources/order_detail.md", "source") is True
    assert pt.validate_routing("wiki/process/refund.md", "process") is True


def test_validate_routing_mismatch():
    # entity 页落在 sources 目录 → 不一致
    assert pt.validate_routing("wiki/sources/order_detail.md", "entity") is False
    # 非 wiki 前缀
    assert pt.validate_routing("md/order_detail.md", "source") is False


def test_sanitize_slug():
    assert pt.sanitize_slug("Entity Order Detail") == "entity_order_detail"
    assert pt.sanitize_slug("order-detail!") == "order_detail"
    assert pt.sanitize_slug("中文") == ""  # 非 [a-z0-9_] 全剔除


def test_slug_from_source_identity():
    # data_table/order_detail.xlsx → 去扩展名 + 多段下划线连
    assert pt.slug_from_source_identity("data_table/order_detail.xlsx") == "data_table_order_detail"
    assert pt.slug_from_source_identity("process/policy.md") == "process_policy"


def test_locked_and_union_fields():
    assert pt.LOCKED_FIELDS == ("type", "title", "created")
    assert pt.UNION_FIELDS == ("sources", "tags", "related")

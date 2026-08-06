import pytest

from kb_retrieval.kb.ingest.wiki import page_types as pt
from kb_retrieval.kb.ingest.wiki.page_type_config import get_registry


def test_page_types_match_registry():
    # PAGE_TYPES 从 page_types.yaml 派生；不再硬编码字面量集合
    assert pt.PAGE_TYPES == frozenset(s.key for s in get_registry().types)


def test_dir_type_mapping_roundtrip():
    # 遍历 registry 逐类型断言 dir↔type 双射（自动覆盖新增类型）
    for spec in get_registry().types:
        assert pt.dir_for_type(spec.key) == spec.dir
        assert pt.type_for_dir(spec.dir) == spec.key
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


def test_validate_routing_processes_alias():
    # LLM 漂移输出复数 processes，应被容忍为合法 process routing
    assert pt.validate_routing("wiki/processes/refund.md", "process") is True
    # 别名不污染其他类型
    assert pt.validate_routing("wiki/processes/refund.md", "entity") is False


def test_normalize_wiki_path():
    assert pt.normalize_wiki_path("wiki/processes/refund.md") == "wiki/process/refund.md"
    # 非别名原样返回
    assert pt.normalize_wiki_path("wiki/sources/x.md") == "wiki/sources/x.md"
    assert pt.normalize_wiki_path("wiki/entities/y.md") == "wiki/entities/y.md"

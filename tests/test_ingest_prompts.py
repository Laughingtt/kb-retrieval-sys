from kb_retrieval.kb.llm import ingest_prompts as p
from kb_retrieval.kb.ingest.wiki.page_type_config import get_registry


def test_step1_messages_contain_required_fields():
    sys_, user = p.build_step1_messages("data_table/order_detail.xlsx", "## 订单\n|order_id|...", "# Wiki Index")
    assert "编目员" in sys_ or "cataloger" in sys_.lower()
    assert "JSON" in sys_
    # 每个 registry 类型键都出现在 step1 system（自动覆盖新增类型）
    for spec in get_registry().types:
        assert spec.key in sys_
    assert "data_table/order_detail.xlsx" in user
    assert "## 订单" in user


def test_step2_messages_contain_file_block_format():
    step1 = {"entities": [{"name": "订单", "slug": "entity_order", "role": "数据表"}], "concepts": [], "processes": [], "summary": "s", "keywords": ["order_id"]}
    sys_, user = p.build_step2_messages("data_table/order_detail.xlsx", "## 订单\n", step1, "# Wiki Index")
    assert "FILE" in sys_
    assert "---FILE:" in sys_
    assert "context only" in sys_.lower() or "do not repeat" in sys_.lower()
    assert "data_table/order_detail.xlsx" in user


def test_step_prompts_single_process_dir_anchored():
    # 对 dir 不等于简单复数的类型，提示词含"单数"锚点（process 命中此规则）
    s1_sys, _ = p.build_step1_messages("process/policy.md", "## 流程", "# Index")
    assert "wiki/process/" in s1_sys
    assert "单数" in s1_sys or "不是 processes" in s1_sys
    # step2 FILE block 行也强化单数
    s2_sys, _ = p.build_step2_messages(
        "process/policy.md", "## 流程",
        {"entities": [], "concepts": [], "processes": [], "summary": "", "keywords": []},
        "# Index",
    )
    assert "单数" in s2_sys or "不是 processes" in s2_sys

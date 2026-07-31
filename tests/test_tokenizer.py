from l1_kb.retrieval.tokenizer import tokenize


def test_english_token():
    toks = tokenize("order_id")
    assert "order_id" in toks


def test_cjk_bigram():
    toks = set(tokenize("订单状态"))
    # CJK bigram：订单/单状/状态 至少含若干
    assert "订单" in toks or "状态" in toks


def test_mixed():
    toks = set(tokenize("order_id 订单状态"))
    assert "order_id" in toks
    assert "订单" in toks or "状态" in toks


def test_empty():
    assert tokenize("") == []


def test_prc_code():
    toks = set(tokenize("PRC-2024-003"))
    # jieba 可能切不准，但整体串或 PRC 应在
    assert "PRC-2024-003" in toks or "PRC" in toks or "2024" in toks

"""分词 jieba + CJK bigram —— M2 设计 §5.2（F7）。

词项 = jieba.cut_for_search 切词 ∪ 连续 CJK 串的 2-gram。
jieba 对未登录词（order_status / PRC-2024-003）切不准时 bigram 兜底。
"""

from __future__ import annotations

import re

import jieba

__all__ = ["tokenize"]

_CJK_RE = re.compile(r"[一-鿿]+")
# 兜底：jieba 会把 order_id 切成 order/_/id，补回蛇形复合词。
_SNAKE_RE = re.compile(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+")


def tokenize(text: str) -> list[str]:
    """返回去重保序的词项列表：jieba 切词 ∪ CJK bigram ∪ 蛇形复合词兜底。"""
    if not text:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for t in jieba.cut_for_search(text):
        if t.strip() and t not in seen:
            seen.add(t)
            tokens.append(t)
    for run in _CJK_RE.findall(text):
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in seen:
                seen.add(bg)
                tokens.append(bg)
    for snake in _SNAKE_RE.findall(text):
        if snake not in seen:
            seen.add(snake)
            tokens.append(snake)
    return tokens

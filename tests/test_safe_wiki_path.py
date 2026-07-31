import pytest

from l1_kb.ingest.wiki.safe_path import is_safe_wiki_path


@pytest.mark.parametrize("path", [
    "wiki/sources/order_detail.md",
    "wiki/entities/entity_order.md",
    "wiki/process/refund.md",
])
def test_safe_paths(path):
    assert is_safe_wiki_path(path) is True


@pytest.mark.parametrize("path", [
    "wiki/../etc/passwd",          # .. 越界
    "wiki/sources/../sources/x.md",  # 含 ..
    "/etc/passwd",                  # 绝对路径
    "C:\\Users\\x.md",              # Windows 盘符
    "md/order_detail.md",           # 非 wiki 前缀
    "wiki/sources/\x00bad.md",      # 控制字符
    "",                             # 空
    "wiki/sources",                 # 无扩展名/非 .md（目录）
])
def test_unsafe_paths(path):
    assert is_safe_wiki_path(path) is False

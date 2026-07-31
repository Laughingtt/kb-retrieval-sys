"""is_safe_wiki_path —— M2 设计 §3.7。

吸收 llm_wiki isSafeIngestPath 原理（Python 重实现，非复制源码）。
LLM 生成的 path 来自不可信文本（源文档可能含 prompt injection），必须校验：
非空、无控制字符、非绝对路径/Windows 盘符、反斜杠归一、任一段含 .. 拒绝、
必须 wiki/ 前缀、必须 .md 结尾。
"""

from __future__ import annotations

import re

__all__ = ["is_safe_wiki_path"]

_CTRL_RE = re.compile(r"[\x00-\x1f]")


def is_safe_wiki_path(path: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    if _CTRL_RE.search(path):
        return False
    norm = path.replace("\\", "/")
    # 绝对路径 / Windows 盘符
    if norm.startswith("/") or re.match(r"^[a-zA-Z]:/", norm):
        return False
    parts = norm.split("/")
    if parts[0] != "wiki":
        return False
    for seg in parts:
        if seg in ("", ".", ".."):
            return False
        if ".." in seg:  # 段内含 ..
            return False
    # 必须是 .md 叶子文件
    if not norm.endswith(".md"):
        return False
    # 禁止生成应用管理文件
    stem = parts[-1][:-3]
    if stem in ("index", "log", "overview"):
        return False
    return True

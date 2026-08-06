"""doc_id 派生 —— PRD §7.1.1, F1（评审 B2 修复）。

doc_id 由**稳定输入**派生，与 LLM 判断解耦：
    doc_id = slug(raw 相对路径) + "__" + sha256(文件字节)[:8]

- category 是 LLM 赋值会漂移，**不进 doc_id**（降为字段）。
- 路径是稳定的真相源（raw 目录结构由人维护），sha256 防内容碰撞。
- 同路径内容变 → sha256 变 → doc_id 变 → 视为"修改"（增量覆盖）。
- related_docs 存 doc_id；因 doc_id 稳定，引用不会因重分类断链。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

__all__ = ["make_doc_id", "slugify_path"]


def slugify_path(rel: Path) -> str:
    """相对路径 → slug。

    规则：去扩展名；目录分隔符 → `_`；仅保留 [a-z0-9_]；其余字符 → `_`；
    连续 `_` 压缩；首尾 `_` 去除；空串兜底为 `doc`。

    例：data_table/order_detail.xlsx → "data_table_order_detail"
    """
    # 取去扩展名后的相对路径字符串（保留目录层级）
    parts = list(rel.with_suffix("").parts)
    raw = "/".join(parts)
    # 非字母数字字符（含中文、斜杠、点）统一替换为下划线
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", raw)
    slug = slug.lower().strip("_")
    return slug or "doc"


def make_doc_id(raw_root: Path, raw_path: Path) -> str:
    """生成稳定 doc_id。

    doc_id = slugify_path(raw_path 相对 raw_root) + "__" + sha256(文件字节)[:8]

    例：raw_root=knowledge_base/raw, raw_path=.../raw/data_table/order_detail.xlsx
        → "data_table_order_detail__a3f9c1e2"
    """
    rel = raw_path.relative_to(raw_root)
    slug = slugify_path(rel)
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()[:8]
    return f"{slug}__{digest}"

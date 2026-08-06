"""页类型配置加载与校验 —— 单一事实源 page_types.yaml。

YAML 驱动 wiki 全链路：提示词、page_types 派生、index.md 渲染、REST API、lint。
路径经 env `KB_PAGE_TYPES_PATH` 覆盖（默认 kb_retrieval/kb/knowledge_base/page_types.yaml），
测试可指向临时 YAML 切换配置（与 config.py 的 env 模式一致）。
文件缺失/损坏 → 硬编码兜底（warn，不抛，保证开箱即用）；
校验失败 → 抛 PageTypeConfigError（fail loud）。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

__all__ = [
    "PageTypeSpec",
    "PageTypeRegistry",
    "PageTypeConfigError",
    "load_spec",
    "get_registry",
]


class PageTypeConfigError(Exception):
    """页类型配置校验失败。"""


_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class PageTypeSpec:
    key: str
    dir: str
    label: str
    description: str
    mandatory: bool = False
    orphan_exempt: bool = False
    xref_check: bool = False
    plural_key: str = ""
    dir_aliases: tuple[str, ...] = ()
    schema_template: str = ""


@dataclass(frozen=True)
class PageTypeRegistry:
    types: tuple[PageTypeSpec, ...]
    by_key: dict[str, PageTypeSpec] = field(default_factory=dict)
    mandatory: PageTypeSpec | None = None


def _default_spec() -> PageTypeRegistry:
    """硬编码兜底（YAML 缺失/损坏时用），等价于当前 4 类。"""
    specs = (
        PageTypeSpec(
            key="source", dir="sources", label="原件摘要",
            description="一份原件的摘要页（每次摄入必产 1 张）",
            mandatory=True, orphan_exempt=True, xref_check=False, plural_key="",
            schema_template="",
        ),
        PageTypeSpec(
            key="entity", dir="entities", label="业务实体",
            description="数据表、API、系统、角色等业务对象",
            plural_key="entities", xref_check=True,
            schema_template='{"name": "...", "slug": "entity_xxx", "role": "...", "exists": false}',
        ),
        PageTypeSpec(
            key="concept", dir="concepts", label="业务概念",
            description="术语、口径、定义",
            plural_key="concepts", xref_check=True,
            schema_template='{"name": "...", "slug": "concept_xxx", "definition": "...", "exists": false}',
        ),
        PageTypeSpec(
            key="process", dir="process", label="流程/制度",
            description="审批流、制度编号、步骤、责任人、上下游、触发条件",
            plural_key="processes", dir_aliases=("processes",), xref_check=False,
            schema_template='{"name": "...", "slug": "process_xxx", "code": "PRC-xxx 或制度编号", "owner": "...", "steps": ["..."], "upstream": "...", "downstream": "...", "exists": false}',
        ),
    )
    return _build_registry(specs)


def _build_registry(specs: tuple[PageTypeSpec, ...]) -> PageTypeRegistry:
    by_key = {s.key: s for s in specs}
    mandatory_list = [s for s in specs if s.mandatory]
    mandatory = mandatory_list[0] if mandatory_list else None
    return PageTypeRegistry(types=specs, by_key=by_key, mandatory=mandatory)


def _default_path() -> Path:
    """默认配置路径：kb_retrieval/kb/knowledge_base/page_types.yaml（基于本文件位置）。"""
    return Path(__file__).resolve().parents[2] / "knowledge_base" / "page_types.yaml"


def _parse_spec(raw: dict) -> PageTypeSpec:
    aliases = raw.get("dir_aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return PageTypeSpec(
        key=str(raw.get("key", "")).strip(),
        dir=str(raw.get("dir", "")).strip(),
        label=str(raw.get("label", "")).strip(),
        description=str(raw.get("description", "")).strip(),
        mandatory=bool(raw.get("mandatory", False)),
        orphan_exempt=bool(raw.get("orphan_exempt", False)),
        xref_check=bool(raw.get("xref_check", False)),
        plural_key=str(raw.get("plural_key", "") or "").strip(),
        dir_aliases=tuple(str(a).strip() for a in aliases if str(a).strip()),
        schema_template=str(raw.get("schema_template", "") or "").strip(),
    )


def _validate(specs: tuple[PageTypeSpec, ...]) -> None:
    if not specs:
        raise PageTypeConfigError("types 为空")

    keys, dirs, plurals, alias_map = set(), set(), set(), {}
    for s in specs:
        for name, val in (("key", s.key), ("dir", s.dir), ("label", s.label)):
            if not val:
                raise PageTypeConfigError(f"类型 {s.key!r} 的 {name} 为空")
        if not _SLUG_RE.match(s.key):
            raise PageTypeConfigError(f"key 非合法 slug（仅 [a-z0-9_]）: {s.key!r}")
        if not _SLUG_RE.match(s.dir):
            raise PageTypeConfigError(f"dir 非合法 slug（仅 [a-z0-9_]）: {s.dir!r}")
        if s.plural_key and not _SLUG_RE.match(s.plural_key):
            raise PageTypeConfigError(f"plural_key 非合法 slug: {s.plural_key!r}")
        if s.key in keys:
            raise PageTypeConfigError(f"key 重复: {s.key!r}")
        if s.dir in dirs:
            raise PageTypeConfigError(f"dir 重复: {s.dir!r}")
        if s.plural_key and s.plural_key in plurals:
            raise PageTypeConfigError(f"plural_key 重复: {s.plural_key!r}")
        for a in s.dir_aliases:
            if a in dirs:
                raise PageTypeConfigError(f"dir_alias {a!r} 与真实 dir 冲突")
            if a in alias_map:
                raise PageTypeConfigError(f"dir_alias {a!r} 重复")
            alias_map[a] = s.dir
        keys.add(s.key)
        dirs.add(s.dir)
        if s.plural_key:
            plurals.add(s.plural_key)

    mandatory = [s for s in specs if s.mandatory]
    if len(mandatory) != 1:
        raise PageTypeConfigError(
            f"必须恰好 1 个 mandatory=true，实际 {len(mandatory)} 个"
        )


def load_spec(path: Path | None = None) -> PageTypeRegistry:
    """加载并校验页类型配置。

    path 为 None 时读 env KB_PAGE_TYPES_PATH，默认 _default_path()。
    文件缺失/解析失败 → _default_spec()（warn 到 stderr，不抛）。
    校验失败 → raise PageTypeConfigError（fail loud）。
    """
    if path is None:
        path = Path(os.environ.get("KB_PAGE_TYPES_PATH", "")) if os.environ.get("KB_PAGE_TYPES_PATH") else _default_path()
    if not path.exists():
        print(f"[warn] page_type_config: 配置缺失，用兜底 4 类: {path}", file=sys.stderr)
        return _default_spec()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        print(f"[warn] page_type_config: 配置解析失败，用兜底 4 类: {e}", file=sys.stderr)
        return _default_spec()
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), list):
        print(f"[warn] page_type_config: 配置结构非法（缺 types 列表），用兜底 4 类: {path}", file=sys.stderr)
        return _default_spec()
    specs = tuple(_parse_spec(r) for r in raw["types"] if isinstance(r, dict))
    _validate(specs)
    return _build_registry(specs)


_REGISTRY: PageTypeRegistry | None = None


def get_registry() -> PageTypeRegistry:
    """返回缓存的 registry（首次调用时加载）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_spec()
    return _REGISTRY


def _reset_cache() -> None:
    """测试钩子：清缓存，使下次 get_registry() 重新读 env/文件。"""
    global _REGISTRY
    _REGISTRY = None

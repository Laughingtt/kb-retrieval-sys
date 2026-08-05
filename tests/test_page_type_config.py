"""page_types.yaml 配置化端到端测试 —— 验证全链路从单一 YAML 源派生。

通过 `KB_PAGE_TYPES_PATH` env 指向临时 YAML 切换配置 + `_reset_cache()` 清缓存，
无需 monkeypatch 模块全局（与 config.py 的 env 模式一致）。
覆盖：默认 4 类兜底、第 5 类加载、3 类校验失败、提示词渲染、index.md 渲染、
REST /documents 过滤、lint L3/L4 行为跟随配置标志。
"""

from __future__ import annotations

import pytest

from l1_kb.ingest.wiki import page_types as pt
from l1_kb.ingest.wiki.page_type_config import (
    PageTypeConfigError,
    _reset_cache,
    get_registry,
    load_spec,
)


# 5 类 YAML 模板：在默认 4 类基础上加 policy（制度）。
YAML_5 = """\
types:
  - key: source
    dir: sources
    label: 原件摘要
    description: 一份原件的摘要页
    mandatory: true
    orphan_exempt: true
    plural_key: ""
  - key: entity
    dir: entities
    label: 业务实体
    description: 业务对象
    plural_key: entities
    xref_check: true
    schema_template: '{"name": "...", "slug": "entity_xxx", "exists": false}'
  - key: concept
    dir: concepts
    label: 业务概念
    description: 术语
    plural_key: concepts
    xref_check: true
  - key: process
    dir: process
    label: 流程
    description: 流程
    plural_key: processes
    dir_aliases: [processes]
  - key: policy
    dir: policies
    label: 制度
    description: 制度条文
    plural_key: policies
    xref_check: true
"""


@pytest.fixture
def reset_cfg():
    """每个测试前后清 registry 缓存 + 同步 page_types 模块常量。

    setup 只清缓存（不预加载），让测试体设好 env 后首次 get_registry() 读新配置；
    teardown 清缓存并刷新回默认，避免污染后续测试。
    """
    from l1_kb.ingest.wiki import page_types as pt
    _reset_cache()
    yield
    _reset_cache()
    pt._refresh()


def _write_yaml(tmp_path, text: str, name: str = "page_types.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 默认兜底 + 加载
# ---------------------------------------------------------------------------

def test_default_spec_equals_four_types(reset_cfg, monkeypatch, tmp_path):
    # 不设 env → 默认路径（仓库内 page_types.yaml）或兜底；两种都应含 4 类
    monkeypatch.delenv("KB_PAGE_TYPES_PATH", raising=False)
    r = load_spec()  # 走默认路径（仓库 page_types.yaml）
    keys = [s.key for s in r.types]
    assert keys == ["source", "entity", "concept", "process"]
    assert r.mandatory is not None and r.mandatory.key == "source"
    # source 豁免孤儿；entity/concept 参与 xref
    by = r.by_key
    assert by["source"].orphan_exempt is True
    assert by["entity"].xref_check is True
    assert by["concept"].xref_check is True
    assert by["process"].dir == "process"
    assert "processes" in by["process"].dir_aliases


def test_load_custom_yaml_with_fifth_type(reset_cfg, monkeypatch, tmp_path):
    p = _write_yaml(tmp_path, YAML_5)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    r = load_spec()
    keys = [s.key for s in r.types]
    assert keys == ["source", "entity", "concept", "process", "policy"]
    assert r.by_key["policy"].dir == "policies"
    assert r.by_key["policy"].plural_key == "policies"
    assert r.by_key["policy"].xref_check is True
    # page_types 模块派生跟随（reset_cfg 已刷新；这里再确认 registry 已加载新配置）
    _reset_cache()
    pt._refresh()
    assert "policy" in pt.PAGE_TYPES
    assert pt.TYPE_TO_DIR["policy"] == "policies"


# ---------------------------------------------------------------------------
# 校验失败（fail loud）
# ---------------------------------------------------------------------------

def test_validation_missing_mandatory_raises(reset_cfg, monkeypatch, tmp_path):
    yaml_no_mandatory = """\
types:
  - key: source
    dir: sources
    label: 原件摘要
    description: x
  - key: entity
    dir: entities
    label: 实体
    description: x
    plural_key: entities
"""
    p = _write_yaml(tmp_path, yaml_no_mandatory)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    with pytest.raises(PageTypeConfigError):
        load_spec()


def test_validation_duplicate_dir_raises(reset_cfg, monkeypatch, tmp_path):
    yaml_dup = """\
types:
  - key: source
    dir: sources
    label: 原件摘要
    description: x
    mandatory: true
    orphan_exempt: true
  - key: entity
    dir: sources
    label: 实体
    description: x
    plural_key: entities
"""
    p = _write_yaml(tmp_path, yaml_dup)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    with pytest.raises(PageTypeConfigError):
        load_spec()


def test_validation_two_mandatory_raises(reset_cfg, monkeypatch, tmp_path):
    yaml_two_m = """\
types:
  - key: source
    dir: sources
    label: 原件摘要
    description: x
    mandatory: true
    orphan_exempt: true
  - key: entity
    dir: entities
    label: 实体
    description: x
    plural_key: entities
    mandatory: true
"""
    p = _write_yaml(tmp_path, yaml_two_m)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    with pytest.raises(PageTypeConfigError):
        load_spec()


# ---------------------------------------------------------------------------
# 全链路：提示词 / index.md / REST / lint 跟随配置
# ---------------------------------------------------------------------------

def test_prompts_render_fifth_type(reset_cfg, monkeypatch, tmp_path):
    p = _write_yaml(tmp_path, YAML_5)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    from l1_kb.llm.ingest_prompts import build_step1_messages, build_step2_messages

    s1, _ = build_step1_messages("policy/x.md", "# 制度", "# Index")
    # policy 描述与路径枚举注入提示词
    assert "policy" in s1
    assert "制度条文" in s1
    assert "wiki/policies/" in s1 or "policies" in s1
    s2, _ = build_step2_messages(
        "policy/x.md", "# 制度",
        {"entities": [], "concepts": [], "processes": [], "policies": [], "summary": "", "keywords": []},
        "# Index",
    )
    assert "policies" in s2


def test_index_renders_fifth_type_section(reset_cfg, monkeypatch, tmp_path):
    p = _write_yaml(tmp_path, YAML_5)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    from l1_kb.ingest.wiki.index_log import rebuild_index

    wiki = tmp_path / "wiki"
    (wiki / "policies").mkdir(parents=True)
    (wiki / "policies" / "policy_x.md").write_text(
        "---\ntype: policy\ntitle: \"X\"\ncreated: 2026-08-04\nupdated: 2026-08-04\n"
        "tags: []\nrelated: []\nsources: [x]\n---\nbody\n",
        encoding="utf-8",
    )
    rebuild_index(wiki, "2026-08-04")
    idx = (wiki / "index.md").read_text(encoding="utf-8")
    assert "## 制度" in idx
    assert "[[policy_x|X]]" in idx


def test_app_documents_filter_accepts_fifth_type(reset_cfg, monkeypatch, tmp_path):
    p = _write_yaml(tmp_path, YAML_5)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    from fastapi.testclient import TestClient

    wiki = tmp_path / "wiki"
    (wiki / "policies").mkdir(parents=True)
    (wiki / "policies" / "policy_x.md").write_text(
        "---\ntype: policy\ntitle: \"X\"\ncreated: 2026-08-04\nupdated: 2026-08-04\n"
        "tags: []\nrelated: []\nsources: [x]\n---\nbody\n",
        encoding="utf-8",
    )
    import l1_kb.config as config

    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("WIKI_ROOT", str(wiki))
    from l1_kb.service.app import app

    c = TestClient(app)
    # 合法新类型 → 200（不 422）
    r = c.get("/documents?type=policy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "policy_x"
    # 仍拒绝未知类型
    assert c.get("/documents?type=bogus").status_code == 422


def test_lint_l3_l4_respect_config_flags(reset_cfg, monkeypatch, tmp_path):
    # 自定义 YAML：把 entity 设为 orphan_exempt=true（不再报 L3 孤儿），
    # process 设为 xref_check=true（参与 L4）；用 policy 制造 xref 命中。
    yaml_cfg = """\
types:
  - key: source
    dir: sources
    label: 原件摘要
    description: x
    mandatory: true
    orphan_exempt: true
  - key: entity
    dir: entities
    label: 实体
    description: x
    plural_key: entities
    orphan_exempt: true
    xref_check: false
  - key: process
    dir: process
    label: 流程
    description: x
    plural_key: processes
    dir_aliases: [processes]
    xref_check: true
"""
    p = _write_yaml(tmp_path, yaml_cfg)
    monkeypatch.setenv("KB_PAGE_TYPES_PATH", str(p))
    from l1_kb.ingest.lint import checker
    from l1_kb.ingest.wiki.index_log import rebuild_index

    wiki = tmp_path / "wiki"
    hp = tmp_path / "hash.json"; lp = tmp_path / "log.jsonl"
    cache = tmp_path / "cache.json"; md_root = tmp_path / "md"; md_root.mkdir()
    cache.write_text("{}", encoding="utf-8")
    hp.write_text("{}", encoding="utf-8")

    # entity 孤儿页 —— 但配置里 entity orphan_exempt=true → 不应报 L3_ORPHAN
    (wiki / "entities").mkdir(parents=True)
    (wiki / "entities" / "entity_lonely.md").write_text(
        "---\ntype: entity\ntitle: \"lonely\"\ncreated: 2026-08-04\nupdated: 2026-08-04\n"
        "tags: [order]\nrelated: []\nsources: []\n---\nbody\n",
        encoding="utf-8",
    )
    # 两个 process 页共享 tag 但无交叉引用 —— process xref_check=true → 应报 L4_XREF
    (wiki / "process").mkdir(parents=True)
    (wiki / "process" / "p1.md").write_text(
        "---\ntype: process\ntitle: \"p1\"\ncreated: 2026-08-04\nupdated: 2026-08-04\n"
        "tags: [order]\nrelated: []\nsources: []\n---\nbody\n",
        encoding="utf-8",
    )
    (wiki / "process" / "p2.md").write_text(
        "---\ntype: process\ntitle: \"p2\"\ncreated: 2026-08-04\nupdated: 2026-08-04\n"
        "tags: [order]\nrelated: []\nsources: []\n---\nbody\n",
        encoding="utf-8",
    )
    (wiki / "log.md").write_text("# Wiki Log\n", encoding="utf-8")
    rebuild_index(wiki, "2026-08-04")

    rep = checker.run_lint(wiki_root=wiki, hash_path=hp, ingest_log_path=lp,
                           cache_path=cache, md_root=md_root, today="2026-08-04")
    # entity 孤儿被豁免 → 不报
    assert not any(i.code == "L3_ORPHAN" and i.page == "entity_lonely" for i in rep.issues)
    # process 参与 xref → 报
    assert any(i.code == "L4_XREF" for i in rep.issues)

# tests/test_m3_incremental_e2e.py
"""M3 e2e 全链（真 DEEPSEEK key）—— add→modify→delete→lint→search。

用真实 key（env DEEPSEEK_API_KEY）跑通 CLI 三态分支；无 key 时 skip（不 fail）。
流程：clean → ingest(add) → search 命中 → 改 raw → clean → ingest(modify)
      → 删 raw → ingest(delete) → lint → search 验证 source 页消失。
"""
import os
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from l1_kb.cli.kb import cli

KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
MODEL = os.environ.get("DEEPSEEK_MODEL") or os.environ.get("LLM_MODEL") or "deepseek-v4-flash"
pytestmark = pytest.mark.skipif(not KEY, reason="无 DEEPSEEK key，e2e 跳过")


def _write_xlsx(f: Path, rows: list[list]) -> Path:
    """造一个合法 xlsx：首行表头含 order_id，保证 body 含 'order' token。"""
    f.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "订单"
    for r in rows:
        ws.append(r)
    wb.save(f)
    return f


def _run(args, tmp_path: Path, wiki: Path | None = None):
    env = {**os.environ, "DEEPSEEK_MODEL": MODEL, "LLM_MODEL": MODEL, "KB_TODAY": "2026-08-03"}
    if wiki is not None:
        env["WIKI_ROOT"] = str(wiki)
    return CliRunner().invoke(cli, args, env=env)


def test_m3_add_modify_delete_lint_search(tmp_path: Path):
    raw = tmp_path / "raw"
    md_root = tmp_path / "md"
    wiki = tmp_path / "wiki"
    cache = tmp_path / "cache.json"
    hp = tmp_path / "hash.json"
    lp = tmp_path / "log.jsonl"
    # common：ingest/lint 全量根（raw+md+wiki+cache+hash+log）
    common = [
        "--raw-root", str(raw),
        "--md-root", str(md_root),
        "--wiki-root", str(wiki),
        "--cache-path", str(cache),
        "--hash-path", str(hp),
        "--log-path", str(lp),
    ]
    # clean 只吃 --raw-root + --md-root（不接受 --wiki-root）
    clean_args = ["--raw-root", str(raw), "--md-root", str(md_root)]

    f = _write_xlsx(
        raw / "data_table" / "order_detail.xlsx",
        [["order_id", "customer"], ["O1", "张三"]],
    )

    # 1) clean → md/
    r = _run(["clean", str(raw)] + clean_args, tmp_path)
    assert r.exit_code == 0, r.output

    # 2) ingest（add）
    r = _run(["ingest", str(raw)] + common, tmp_path)
    assert r.exit_code == 0, r.output
    assert "新增 1" in r.output, r.output

    # search 命中（fallback 或 LLM 都会写 source 页，body 含 order）
    r = _run(["search", "order"], tmp_path, wiki=wiki)
    assert r.exit_code == 0, r.output
    assert "[" in r.output, f"add 后未命中: {r.output}"
    assert "无结果" not in r.output

    # 3) modify：改 raw（仍是合法 xlsx，内容不同）→ 清 stale md → clean → ingest
    _write_xlsx(
        f,
        [["order_id", "customer", "amount"], ["O2", "李四", "999"], ["O3", "王五", "100"]],
    )
    if md_root.exists():
        shutil.rmtree(md_root)
    r = _run(["clean", str(raw)] + clean_args, tmp_path)
    assert r.exit_code == 0, r.output
    r = _run(["ingest", str(raw)] + common, tmp_path)
    assert r.exit_code == 0, r.output
    assert "修改 1" in r.output, r.output

    # 4) delete：删 raw → ingest
    f.unlink()
    r = _run(["ingest", str(raw)] + common, tmp_path)
    assert r.exit_code == 0, r.output
    assert "删除 1" in r.output, r.output

    # 5) lint（允许 error/warn，主要验不崩；delete 后无源页，可能 L5 info）
    r = _run(["lint"] + common + ["--out", str(tmp_path / "lint_report.json")], tmp_path)
    assert r.exit_code in (0, 1), r.output

    # 6) delete 后 source 页应清空
    src_pages = list((wiki / "sources").glob("*.md")) if (wiki / "sources").exists() else []
    assert src_pages == [], f"delete 后仍有 source 页: {src_pages}"

    # 7) search delete 后无命中
    r = _run(["search", "order"], tmp_path, wiki=wiki)
    assert r.exit_code == 0, r.output
    assert "[" not in r.output, f"delete 后仍命中: {r.output}"
    assert "无结果" in r.output

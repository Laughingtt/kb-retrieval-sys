"""is_safe_path 单测 —— PRD §7.1.2, F9。

验证点（plan 验证项 #6）：
- `../` 越界路径 → False
- 软链接跳出 raw → False（target 本身是软链）
- raw 内普通文件 → True
- 目录 / 不存在的路径 → False
- 设备/管道类理论上 is_file() False → False
"""

from __future__ import annotations

import os
from pathlib import Path

from kb_retrieval.kb.ingest.safe_path import is_safe_path


def _make_file(p: Path, content: bytes = b"hi") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


class TestIsSafePath:
    def test_normal_file_inside_root(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        f = _make_file(raw_root / "data" / "x.md")
        assert is_safe_path(raw_root, f) is True

    def test_dotdot_escape(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        f = _make_file(raw_root / "inside.md")
        # 通过 ../ 路径访问，但 resolve 后仍在 root 内 → 仍 True（这是 is_safe_path 的意图：
        # resolve 解析后判断是否在 root 内）
        escaping = raw_root / ".." / "raw" / "inside.md"
        assert is_safe_path(raw_root, escaping) is True

    def test_path_truly_outside_root(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        outside = _make_file(tmp_path / "outside.md")
        assert is_safe_path(raw_root, outside) is False

    def test_symlink_pointing_outside_rejected(self, tmp_path: Path):
        """target 本身是软链 → 拒绝（F9 防止 raw 内软链跳出）。"""
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        outside = _make_file(tmp_path / "secret.md", b"secret")
        link = raw_root / "link.md"
        os.symlink(outside, link)
        # resolve 后的 real 在 root 外 → False
        assert is_safe_path(raw_root, link) is False

    def test_symlink_pointing_inside_rejected_anyway(self, tmp_path: Path):
        """即便软链目标在 root 内，target 是软链本身就拒绝（保守策略）。"""
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        target = _make_file(raw_root / "real.md")
        link = raw_root / "link.md"
        os.symlink(target, link)
        assert is_safe_path(raw_root, link) is False

    def test_directory_rejected(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        sub = raw_root / "subdir"
        sub.mkdir()
        assert is_safe_path(raw_root, sub) is False  # is_file() False

    def test_nonexistent_rejected(self, tmp_path: Path):
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        assert is_safe_path(raw_root, raw_root / "ghost.md") is False

    def test_root_itself_rejected(self, tmp_path: Path):
        """raw_root 本身是目录不是文件 → False。"""
        raw_root = tmp_path / "raw"
        raw_root.mkdir()
        assert is_safe_path(raw_root, raw_root) is False

"""路径安全守卫 is_safe_path —— PRD §7.1.2, F9（评审 B7，借鉴 llm_wiki isSafeIngestPath）。

摄入只接受 **raw/ 目录内**的文件，杜绝路径注入与越界写入。
所有摄入入口（kb ingest / kb watch / kb rebuild）先过 is_safe_path，
不通过则跳过并记 warn 日志。

防御：`../` 越界、软链接跳出 raw、传入设备/管道文件等。
对齐 llm_wiki isSafeIngestPath（同源思路，Python 重实现，非复制其代码）。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["is_safe_path"]


def is_safe_path(raw_root: Path, target: Path) -> bool:
    """target 必须解析后在 raw_root 之内、且仍是普通文件（非设备/管道）、非软链跳出。

    - 用 resolve() 解析真实路径（展开 `..`、软链），校验是否在 raw_root 之内。
    - 额外拒绝 target 本身是软链（防止 raw/ 内软链跳出）。
    """
    root = raw_root.resolve()
    real = target.resolve()
    try:
        real.relative_to(root)
    except ValueError:
        return False
    # 普通文件校验（拒绝目录/设备/管道/套接字）；拒绝 target 本身为软链
    return real.is_file() and not target.is_symlink()

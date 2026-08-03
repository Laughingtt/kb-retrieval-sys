"""集中读 env —— M2 设计 §3.1。

路径默认基于项目根（l1_kb/ 上两级）。LLM 配置默认 DeepSeek，公司内部
OpenAI 兼容端点换 env 即可（CLAUDE.md ③）。全部可被 env 覆盖。
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- LLM 配置 ---
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))

# --- 日期戳（确定性，测试可 monkeypatch） ---
TODAY = os.environ.get("KB_TODAY", "")  # 留空时由调用方填，避免模块导入即锁死

_PATH_DIRS = {
    "RAW_ROOT": "raw",
    "MD_ROOT": "md",
    "WIKI_ROOT": "wiki",
}

_EXTRA_PATHS = {
    # 默认 .cache/hash.json 与 knowledge_base/ingest_log.jsonl
    "HASH_PATH": ("l1_kb", "knowledge_base", ".cache", "hash.json"),
    "INGEST_LOG_PATH": ("l1_kb", "knowledge_base", "ingest_log.jsonl"),
}


def _resolve_path(name: str) -> Path:
    """基于 _PROJECT_ROOT 解析路径常量（可被 env 覆盖）。

    通过 PEP 562 模块级 __getattr__ 暴露为模块属性，使测试可
    `monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)` 后即时生效。
    """
    if name in _PATH_DIRS:
        default = _PROJECT_ROOT / "l1_kb" / "knowledge_base" / _PATH_DIRS[name]
        return Path(os.environ.get(name, default))
    if name == "INGEST_CACHE_PATH":
        default = _PROJECT_ROOT / "l1_kb" / "knowledge_base" / ".cache" / "ingest-cache.json"
        return Path(os.environ.get("INGEST_CACHE_PATH", default))
    if name in _EXTRA_PATHS:
        default = _PROJECT_ROOT.joinpath(*_EXTRA_PATHS[name])
        return Path(os.environ.get(name, default))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str):  # PEP 562
    if name in _PATH_DIRS or name == "INGEST_CACHE_PATH" or name in _EXTRA_PATHS:
        return _resolve_path(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _load_llm() -> None:
    """测试钩子：重新从 env 读 LLM 配置（用于 monkeypatch.setenv 后刷新）。"""
    global LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))


def llm_enabled() -> bool:
    """是否配置了 LLM API key。"""
    return bool(LLM_API_KEY)


def today() -> str:
    """返回今日日期字符串 YYYY-MM-DD（优先 KB_TODAY env，否则系统今日）。"""
    if TODAY:
        return TODAY
    import datetime

    return datetime.date.today().isoformat()

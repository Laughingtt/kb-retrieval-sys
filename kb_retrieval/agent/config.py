"""L2 配置 —— 环境变量可覆盖（与 kb_retrieval/kb/config.py 同风格）。

真 key 只从 os.environ 取，绝不落盘。不引入 python-dotenv。
"""
from __future__ import annotations

import os

__all__ = ["reload", "llm_enabled"]

# 模块级常量：import 时从 env 读一次；reload() 重新读。
KB_BASE_URL: str = ""
LLM_BASE_URL: str = ""
LLM_API_KEY: str = ""
LLM_MODEL: str = ""
LLM_TIMEOUT: int = 60
KB_TIMEOUT: int = 10
MAX_TURNS: int = 10
LLM_TEMPERATURE: float = 0.3


def reload() -> None:
    """重新从 env 读配置（测试 monkeypatch.setenv 后调用）。"""
    global KB_BASE_URL, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
    global LLM_TIMEOUT, KB_TIMEOUT, MAX_TURNS, LLM_TEMPERATURE
    KB_BASE_URL = os.environ.get("KB_BASE_URL", "http://127.0.0.1:8011")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))
    KB_TIMEOUT = int(os.environ.get("KB_TIMEOUT", "10"))
    MAX_TURNS = int(os.environ.get("MAX_TURNS", "10"))
    LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.3"))


def llm_enabled() -> bool:
    return bool(LLM_API_KEY)


reload()  # import 时读一次

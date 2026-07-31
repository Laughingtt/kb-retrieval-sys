import os
from pathlib import Path

from l1_kb import config


def test_paths_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    assert config.RAW_ROOT == tmp_path / "l1_kb" / "knowledge_base" / "raw"
    assert config.WIKI_ROOT == tmp_path / "l1_kb" / "knowledge_base" / "wiki"
    assert config.INGEST_CACHE_PATH.name == "ingest-cache.json"


def test_llm_config_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://internal/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "internal-model")
    config._load_llm()
    assert config.LLM_BASE_URL == "https://internal/v1"
    assert config.LLM_API_KEY == "sk-test"
    assert config.LLM_MODEL == "internal-model"
    assert config.llm_enabled() is True


def test_llm_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config._load_llm()
    assert config.llm_enabled() is False

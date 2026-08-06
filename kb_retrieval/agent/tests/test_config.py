# kb_retrieval/agent/tests/test_config.py
import importlib


def test_defaults_and_env_override(monkeypatch):
    import kb_retrieval.agent.config as config
    for k in ("KB_BASE_URL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
              "LLM_TIMEOUT", "KB_TIMEOUT", "MAX_TURNS", "LLM_TEMPERATURE"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(config)
    assert config.KB_BASE_URL == "http://127.0.0.1:8011"
    assert config.LLM_BASE_URL == "https://api.deepseek.com/v1"
    assert config.LLM_MODEL == "deepseek-v4-flash"
    assert config.LLM_TIMEOUT == 60
    assert config.KB_TIMEOUT == 10
    assert config.MAX_TURNS == 10
    assert config.LLM_TEMPERATURE == 0.3
    assert config.llm_enabled() is False

    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "other-model")
    monkeypatch.setenv("MAX_TURNS", "5")
    config.reload()
    assert config.llm_enabled() is True
    assert config.LLM_MODEL == "other-model"
    assert config.MAX_TURNS == 5

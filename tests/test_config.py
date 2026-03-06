"""Tests for configuration management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from msagent.config import (
    AppConfig,
    ConfigManager,
    LLMConfig,
    MCPConfig,
)


LLM_ENV_KEYS = [
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "CUSTOM_API_KEY",
    "CUSTOM_BASE_URL",
    "CUSTOM_MODEL",
]


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each config test in an empty working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure external env vars don't leak into tests."""
    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def create_manager(base_dir: Path) -> ConfigManager:
    """Create a config manager that writes only under test temp dir."""
    manager = ConfigManager()
    manager.CONFIG_DIR = base_dir / ".config" / "msagent"
    manager.CONFIG_FILE = manager.CONFIG_DIR / "config.json"
    return manager


def test_llm_config_is_configured() -> None:
    config = LLMConfig()
    assert not config.is_configured()

    config.api_key = "test-key"
    assert config.is_configured()


def test_llm_config_is_configured_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    config = LLMConfig(provider="openai", api_key_env="OPENAI_API_KEY")
    assert config.is_configured()


def test_resolve_max_tokens_auto_by_model() -> None:
    deepseek_chat = LLMConfig(model="deepseek-chat", max_tokens=0)
    deepseek_reasoner = LLMConfig(model="deepseek-reasoner", max_tokens=0)
    explicit = LLMConfig(model="deepseek-chat", max_tokens=2048)

    assert deepseek_chat.is_max_tokens_auto() is True
    assert deepseek_chat.resolve_max_tokens() is None
    assert deepseek_reasoner.resolve_max_tokens() is None
    assert explicit.is_max_tokens_auto() is False
    assert explicit.resolve_max_tokens() == 2048


def test_negative_max_tokens_resets_to_auto(
    isolated_workspace: Path,
    clean_llm_env: None,
) -> None:
    local_config_path = isolated_workspace / "config.json"
    local_config_path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "openai",
                    "api_key_env": "OPENAI_API_KEY",
                    "model": "gpt-4o-mini",
                    "max_tokens": -1,
                },
                "mcp_servers": [],
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )
    manager = create_manager(isolated_workspace)
    config = manager.load_config()
    assert config.llm.max_tokens == 0
    assert config.llm.resolve_max_tokens() is None


def test_mcp_config_model_fields() -> None:
    config = MCPConfig(name="test-server", command="python", args=["server.py"], enabled=True)
    assert config.name == "test-server"
    assert config.command == "python"
    assert config.args == ["server.py"]
    assert config.enabled is True


def test_load_default_config(isolated_workspace: Path, clean_llm_env: None) -> None:
    manager = create_manager(isolated_workspace)
    config = manager.load_config()

    assert isinstance(config, AppConfig)
    assert config.llm.provider == "openai"
    assert config.llm.model == "gpt-4o-mini"
    assert config.llm.api_key == ""
    assert config.llm.max_tokens == 0


def test_local_config_file_has_priority(
    isolated_workspace: Path,
    clean_llm_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_config_path = isolated_workspace / "config.json"
    local_config_path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "gemini",
                    "api_key": "from-local-file",
                    "base_url": "",
                    "model": "gemini-2.0-flash",
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                "mcp_servers": [],
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    manager = create_manager(isolated_workspace)
    config = manager.load_config()

    assert config.llm.provider == "gemini"
    assert config.llm.api_key == "from-local-file"


def test_load_legacy_deepseek_max_tokens_defaults_to_auto(
    isolated_workspace: Path,
    clean_llm_env: None,
) -> None:
    local_config_path = isolated_workspace / "config.json"
    local_config_path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "openai",
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "temperature": 0.0,
                    "max_tokens": 4096,
                },
                "mcp_servers": [],
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )

    manager = create_manager(isolated_workspace)
    config = manager.load_config()
    assert config.llm.max_tokens == 0
    assert config.llm.resolve_max_tokens() is None


def test_load_plaintext_api_key_auto_scrubs_file(
    isolated_workspace: Path,
    clean_llm_env: None,
) -> None:
    local_config_path = isolated_workspace / "config.json"
    local_config_path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "openai",
                    "api_key": "legacy-plaintext-key",
                    "base_url": "",
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                "mcp_servers": [],
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )

    manager = create_manager(isolated_workspace)
    config = manager.load_config()
    persisted = json.loads(local_config_path.read_text(encoding="utf-8"))

    assert config.llm.api_key == "legacy-plaintext-key"
    assert "api_key" not in persisted["llm"]
    assert persisted["llm"]["api_key_env"] == "OPENAI_API_KEY"


def test_save_and_load_config_round_trip(
    isolated_workspace: Path,
    clean_llm_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = create_manager(isolated_workspace)
    config = AppConfig()
    config.llm.provider = "openai"
    config.llm.api_key = "test-key"
    config.llm.model = "gpt-4"

    manager.save_config(config)
    persisted = json.loads(manager.CONFIG_FILE.read_text(encoding="utf-8"))
    assert "api_key" not in persisted["llm"]
    assert persisted["llm"]["api_key_env"] == "OPENAI_API_KEY"

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    manager._config = None

    loaded = manager.load_config()
    assert loaded.llm.api_key == "test-key"
    assert loaded.llm.model == "gpt-4"


def test_load_openai_env_config(
    isolated_workspace: Path,
    clean_llm_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")

    manager = create_manager(isolated_workspace)
    config = manager.load_config()

    assert config.llm.provider == "openai"
    assert config.llm.api_key == "openai-key"
    assert config.llm.model == "gpt-4.1-mini"


def test_load_anthropic_env_config(
    isolated_workspace: Path,
    clean_llm_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-3-7-sonnet")

    manager = create_manager(isolated_workspace)
    config = manager.load_config()

    assert config.llm.provider == "anthropic"
    assert config.llm.api_key == "anthropic-key"
    assert config.llm.model == "claude-3-7-sonnet"


def test_custom_api_env_takes_final_priority(
    isolated_workspace: Path,
    clean_llm_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("CUSTOM_API_KEY", "custom-key")
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://custom.local/v1")
    monkeypatch.setenv("CUSTOM_MODEL", "custom-model")

    manager = create_manager(isolated_workspace)
    config = manager.load_config()

    assert config.llm.provider == "custom"
    assert config.llm.api_key == "custom-key"
    assert config.llm.base_url == "https://custom.local/v1"
    assert config.llm.model == "custom-model"


def test_add_remove_and_filter_mcp_servers(
    isolated_workspace: Path,
    clean_llm_env: None,
) -> None:
    manager = create_manager(isolated_workspace)
    manager._config = AppConfig(mcp_servers=[])

    manager.add_mcp_server(MCPConfig(name="one", command="python", enabled=True))
    manager.add_mcp_server(MCPConfig(name="two", command="node", enabled=False))
    manager.add_mcp_server(MCPConfig(name="one", command="uvx", enabled=True))

    assert [server.name for server in manager.get_config().mcp_servers] == ["two", "one"]
    assert [server.name for server in manager.get_mcp_servers()] == ["one"]

    assert manager.remove_mcp_server("one") is True
    assert manager.remove_mcp_server("missing") is False

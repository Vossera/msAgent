"""Configuration management for msagent."""

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


PROVIDER_API_KEY_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "custom": "CUSTOM_API_KEY",
}

LEGACY_DEEPSEEK_MAX_TOKENS = 4096


def get_default_api_key_env(provider: str) -> str:
    """Get the default API key environment variable name for a provider."""
    return PROVIDER_API_KEY_ENV_MAP.get((provider or "").lower().strip(), "")


class LLMConfig(BaseModel):
    """Configuration for LLM providers."""
    
    provider: Literal["openai", "anthropic", "gemini", "custom"] = "openai"
    api_key: str = Field(default="", exclude=True, repr=False)
    api_key_env: str = ""
    base_url: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 0

    def resolve_api_key(self) -> str:
        """Resolve API key from runtime value or environment variables."""
        if self.api_key:
            return self.api_key

        if self.api_key_env:
            return os.getenv(self.api_key_env, "")

        default_env = get_default_api_key_env(self.provider)
        if default_env:
            return os.getenv(default_env, "")
        return ""
    
    def is_configured(self) -> bool:
        """Check if the configuration is valid."""
        return bool(self.resolve_api_key())

    def is_max_tokens_auto(self) -> bool:
        """Whether max_tokens is auto-derived from model."""
        return self.max_tokens <= 0

    def resolve_max_tokens(self) -> int | None:
        """Resolve output max tokens; None means use provider default."""
        if self.max_tokens > 0:
            return self.max_tokens
        return None


class MCPConfig(BaseModel):
    """Configuration for MCP server."""
    
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class DeepAgentsConfig(BaseModel):
    """Configuration for deepagents features."""

    skills: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)
    recursion_limit: int = Field(default=80, ge=1)


def get_default_mcp_servers() -> list[MCPConfig]:
    """Get default MCP servers."""
    return [
        MCPConfig(
            name="msprof-mcp",
            command="msprof-mcp",
            args=[],
            enabled=True
        )
    ]


class AppConfig(BaseSettings):
    """Application configuration."""
    
    # LLM Configuration
    llm: LLMConfig = Field(default_factory=LLMConfig)
    
    # MCP Servers Configuration
    mcp_servers: list[MCPConfig] = Field(default_factory=get_default_mcp_servers)

    # deepagents Configuration
    deepagents: DeepAgentsConfig = Field(default_factory=DeepAgentsConfig)
    
    # UI Configuration
    theme: Literal["dark", "light"] = "dark"
    
    class Config:
        env_prefix = "MSAGENT_"
        env_nested_delimiter = "__"


class ConfigManager:
    """Manages configuration loading and saving."""
    
    CONFIG_DIR = Path.home() / ".config" / "msagent"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    
    def __init__(self):
        self._config: AppConfig | None = None
        self._config_path: Path | None = None
    
    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _hydrate_api_key_from_env(self, llm_config: LLMConfig) -> None:
        """Resolve and populate runtime api_key from configured/default env vars."""
        configured_env = (llm_config.api_key_env or "").strip()
        if configured_env:
            env_value = os.getenv(configured_env, "")
            if env_value:
                llm_config.api_key = env_value
                return

        default_env = get_default_api_key_env(llm_config.provider)
        if default_env:
            env_value = os.getenv(default_env, "")
            if env_value:
                llm_config.api_key = env_value
                if not llm_config.api_key_env:
                    llm_config.api_key_env = default_env

    def _apply_provider_env_overrides(self, llm_config: LLMConfig) -> None:
        """Apply provider/model defaults from environment variables."""
        if os.getenv("OPENAI_API_KEY"):
            llm_config.provider = "openai"
            llm_config.api_key_env = "OPENAI_API_KEY"
            llm_config.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif os.getenv("ANTHROPIC_API_KEY"):
            llm_config.provider = "anthropic"
            llm_config.api_key_env = "ANTHROPIC_API_KEY"
            llm_config.model = os.getenv(
                "ANTHROPIC_MODEL",
                "claude-3-5-sonnet-20241022",
            )
        elif os.getenv("GEMINI_API_KEY"):
            llm_config.provider = "gemini"
            llm_config.api_key_env = "GEMINI_API_KEY"
            llm_config.model = os.getenv("GEMINI_MODEL", "gemini-pro")

        if os.getenv("CUSTOM_API_KEY"):
            llm_config.provider = "custom"
            llm_config.api_key_env = "CUSTOM_API_KEY"
            llm_config.base_url = os.getenv("CUSTOM_BASE_URL", "")
            llm_config.model = os.getenv("CUSTOM_MODEL", "")

    def _normalize_llm_config(self, llm_config: LLMConfig) -> None:
        """Normalize runtime LLM config while keeping persisted config secret-free."""
        if llm_config.max_tokens < 0:
            llm_config.max_tokens = 0
        if (
            llm_config.max_tokens == LEGACY_DEEPSEEK_MAX_TOKENS
            and (llm_config.model or "").lower().startswith("deepseek-")
        ):
            llm_config.max_tokens = 0
        if llm_config.api_key and not llm_config.api_key_env:
            default_env = get_default_api_key_env(llm_config.provider)
            if default_env:
                llm_config.api_key_env = default_env
        self._hydrate_api_key_from_env(llm_config)

    def _has_plaintext_api_key(self, data: dict[str, Any]) -> bool:
        """Check if raw config payload contains a plaintext API key."""
        llm_data = data.get("llm")
        if not isinstance(llm_data, dict):
            return False
        api_key = llm_data.get("api_key")
        return isinstance(api_key, str) and bool(api_key.strip())
    
    def load_config(self) -> AppConfig:
        """Load configuration from file or create default."""
        if self._config is not None:
            return self._config
            
        # Check for local config.json first
        local_config = Path.cwd() / "config.json"
        if local_config.exists():
            try:
                with open(local_config, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = AppConfig(**data)
                self._normalize_llm_config(self._config.llm)
                self._config_path = local_config
                if self._has_plaintext_api_key(data):
                    self.save_config(self._config)
                # Ensure global config dir exists anyway for saving global preferences if needed
                self._ensure_config_dir()
                return self._config
            except Exception:
                pass
        
        self._ensure_config_dir()
        
        # Try to load from file
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = AppConfig(**data)
                self._normalize_llm_config(self._config.llm)
                self._config_path = self.CONFIG_FILE
                if self._has_plaintext_api_key(data):
                    self.save_config(self._config)
                return self._config
            except Exception:
                pass
        
        # Try to load from environment variables
        self._config = AppConfig()
        self._config_path = self.CONFIG_FILE
        self._apply_provider_env_overrides(self._config.llm)
        self._normalize_llm_config(self._config.llm)
        
        return self._config
    
    def save_config(self, config: AppConfig) -> None:
        """Save configuration to file."""
        self._config = config
        self._normalize_llm_config(self._config.llm)
        target_path = self._config_path or self.CONFIG_FILE
        if target_path == self.CONFIG_FILE:
            self._ensure_config_dir()
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
        try:
            os.chmod(target_path, 0o600)
        except OSError:
            pass
    
    def get_config(self) -> AppConfig:
        """Get current configuration."""
        if self._config is None:
            return self.load_config()
        return self._config
    
    def update_llm_config(self, llm_config: LLMConfig) -> None:
        """Update LLM configuration."""
        config = self.get_config()
        config.llm = llm_config
        self.save_config(config)
    
    def add_mcp_server(self, mcp_config: MCPConfig) -> None:
        """Add an MCP server configuration."""
        config = self.get_config()
        # Remove existing server with same name
        config.mcp_servers = [s for s in config.mcp_servers if s.name != mcp_config.name]
        config.mcp_servers.append(mcp_config)
        self.save_config(config)
    
    def remove_mcp_server(self, name: str) -> bool:
        """Remove an MCP server configuration."""
        config = self.get_config()
        original_len = len(config.mcp_servers)
        config.mcp_servers = [s for s in config.mcp_servers if s.name != name]
        if len(config.mcp_servers) < original_len:
            self.save_config(config)
            return True
        return False
    
    def get_mcp_servers(self) -> list[MCPConfig]:
        """Get all enabled MCP server configurations."""
        config = self.get_config()
        return [s for s in config.mcp_servers if s.enabled]


# Global config manager instance
config_manager = ConfigManager()

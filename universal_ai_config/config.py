"""
Unified configuration management for AI providers.
MCP servers are kept in a separate mcp-config.json file.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional
from .environment import AgentEnv


class ConfigError(Exception):
    """Configuration-related errors."""

    pass


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file with error handling."""
    try:
        with open(path, "r") as f:
            data: Dict[str, Any] = json.load(f)
            return data
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {path}: {e}")
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")


def save_json(path: Path, data: Dict[str, Any], indent: int = 2) -> None:
    """Save JSON file with error handling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=indent)


class UnifiedConfig:
    """Manages unified AI configuration across all providers."""

    def __init__(self, env: Optional[AgentEnv] = None):
        self.env = env or AgentEnv()
        self._unified_config: Optional[Dict[str, Any]] = None

    @property
    def unified_config_path(self) -> Path:
        """Path to the unified config file."""
        return self.env.config / "config.json"

    @property
    def mcp_config_path(self) -> Path:
        """Path to the MCP config file."""
        return self.env.config / "mcp-config.json"

    def load_unified(self, include_mcp: bool = True) -> Dict[str, Any]:
        """Load the unified configuration.

        If include_mcp is True, MCP servers from mcp-config.json are merged
        into the returned config under the 'mcpServers' key.
        """
        if self._unified_config is None:
            path = self.unified_config_path
            if not path.exists():
                config = self._get_default_config()
            else:
                config = load_json(path)
            self._unified_config = config
        else:
            config = self._unified_config

        if include_mcp:
            config = config.copy()
            config["mcpServers"] = self.load_mcp_servers()

        return config

    def load_mcp_servers(self) -> Dict[str, Any]:
        """Load MCP servers from mcp-config.json."""
        if not self.mcp_config_path.exists():
            return {}
        try:
            mcp_config = load_json(self.mcp_config_path)
            servers: Dict[str, Any] = mcp_config.get("mcpServers", {})
            return servers
        except ConfigError:
            return {}

    def save_unified(self, config: Dict[str, Any]) -> None:
        """Save the unified configuration.

        MCP servers are stripped from config.json and saved to mcp-config.json.
        """
        config = config.copy()

        # Extract MCP servers and save separately
        mcp_servers = config.pop("mcpServers", None)
        if mcp_servers is not None:
            self.save_mcp_servers(mcp_servers)

        save_json(self.unified_config_path, config)
        self._unified_config = config

    def save_mcp_servers(self, mcp_servers: Dict[str, Any]) -> None:
        """Save MCP servers to mcp-config.json."""
        mcp_config = {"mcpServers": mcp_servers}
        save_json(self.mcp_config_path, mcp_config)

    def add_mcp_server(self, name: str, config: Dict[str, Any]) -> None:
        """Add or update an MCP server."""
        mcp_servers = self.load_mcp_servers()
        mcp_servers[name] = config
        self.save_mcp_servers(mcp_servers)

    def remove_mcp_server(self, name: str) -> None:
        """Remove an MCP server."""
        mcp_servers = self.load_mcp_servers()
        if name in mcp_servers:
            del mcp_servers[name]
            self.save_mcp_servers(mcp_servers)

    def get_provider_config(self, provider: str) -> Dict[str, Any]:
        """Get configuration for a specific provider."""
        unified = self.load_unified()

        # Start with shared settings
        config = unified.get("shared", {}).copy()

        # Apply provider-specific overrides
        provider_settings = unified.get("providers", {}).get(provider, {})
        config = deep_merge(config, provider_settings)

        # Add shared resources
        config["mcpServers"] = unified.get("mcpServers", {})
        config["skills"] = unified.get("skills", {})

        return config

    def get_merged_config(self, cwd: Optional[Path] = None) -> Dict[str, Any]:
        """Get merged configuration from all sources in precedence order."""
        env = AgentEnv()
        config_paths = env.get_config_precedence(cwd)

        # Start with unified user config (including MCP)
        merged = self.load_unified(include_mcp=True)

        # Merge project configs (lowest to highest priority)
        for path in reversed(config_paths):
            try:
                project_config = load_json(path)
                merged = deep_merge(merged, project_config)

                # Also merge project MCP config if it exists
                mcp_path = path.parent / "mcp-config.json"
                if mcp_path.exists():
                    project_mcp = load_json(mcp_path)
                    if "mcpServers" in project_mcp:
                        merged.setdefault("mcpServers", {})
                        merged["mcpServers"] = deep_merge(
                            merged["mcpServers"], project_mcp["mcpServers"]
                        )

                # Merge project local MCP config if it exists
                local_mcp_path = path.parent / "mcp-config.local.json"
                if local_mcp_path.exists():
                    local_mcp = load_json(local_mcp_path)
                    if "mcpServers" in local_mcp:
                        merged.setdefault("mcpServers", {})
                        merged["mcpServers"] = deep_merge(
                            merged["mcpServers"], local_mcp["mcpServers"]
                        )
            except ConfigError:
                continue

        return merged

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration structure."""
        return {
            "shared": {},
            "providers": {},
            "skills": {"enabled": [], "paths": [str(self.env.skills), ".ai/skills"]},
            "read_config_from": {"windsurf": False, "claude": False},
        }

    def update_provider(self, provider: str, settings: Dict[str, Any]) -> None:
        """Update settings for a specific provider."""
        unified = self.load_unified(include_mcp=False)

        if "providers" not in unified:
            unified["providers"] = {}

        unified["providers"][provider] = deep_merge(
            unified["providers"].get(provider, {}), settings
        )

        self.save_unified(unified)

    def update_shared(self, settings: Dict[str, Any]) -> None:
        """Update shared settings."""
        unified = self.load_unified(include_mcp=False)
        unified["shared"] = deep_merge(unified.get("shared", {}), settings)
        self.save_unified(unified)

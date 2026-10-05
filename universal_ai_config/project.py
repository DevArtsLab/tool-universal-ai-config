"""
Project-local configuration management.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from .environment import AgentEnv, find_project_root
from .config import deep_merge, load_json, save_json, ConfigError


class ProjectConfig:
    """Manages project-local AI configuration."""

    def __init__(self, project_root: Optional[Path] = None, env: Optional[AgentEnv] = None):
        self.env = env or AgentEnv()
        self.project_root = project_root or find_project_root()
        self.ai_dir = self.project_root / ".ai" if self.project_root else None

    def is_in_project(self) -> bool:
        """Check if currently in a project directory."""
        return self.ai_dir is not None and self.ai_dir.exists()

    def _require_ai_dir(self) -> Path:
        """Return the .ai/ dir or raise if not in a project."""
        if self.ai_dir is None:
            raise ConfigError("Not in a project directory")
        return self.ai_dir

    def get_project_config(self) -> Dict[str, Any]:
        """Get project configuration (merged with local overrides)."""
        if not self.is_in_project():
            return {}
        ai_dir = self.ai_dir
        assert ai_dir is not None

        config = {}

        # Load base project config
        config_path = ai_dir / "config.json"
        if config_path.exists():
            try:
                config = load_json(config_path)
            except ConfigError:
                pass

        # Merge local overrides
        local_path = ai_dir / "config.local.json"
        if local_path.exists():
            try:
                local_config = load_json(local_path)
                config = deep_merge(config, local_config)
            except ConfigError:
                pass

        return config

    def save_project_config(self, config: Dict[str, Any], local: bool = False) -> None:
        """Save project configuration."""
        if not self.is_in_project():
            raise ConfigError("Not in a project directory")

        config_path = self._require_ai_dir() / ("config.local.json" if local else "config.json")
        save_json(config_path, config)

    def update_project_config(self, settings: Dict[str, Any], local: bool = False) -> None:
        """Update project configuration with new settings."""
        if not self.is_in_project():
            raise ConfigError("Not in a project directory")

        config_path = self._require_ai_dir() / ("config.local.json" if local else "config.json")

        if config_path.exists():
            existing = load_json(config_path)
            merged = deep_merge(existing, settings)
        else:
            merged = settings

        save_json(config_path, merged)

    def get_project_skills(self) -> List[Path]:
        """Get all project skill directories."""
        if not self.is_in_project():
            return []

        ai_dir = self.ai_dir
        assert ai_dir is not None
        skills_dir = ai_dir / "skills"
        if not skills_dir.exists():
            return []

        return list(skills_dir.glob("*/SKILL.md"))

    def get_project_rules(self) -> Optional[str]:
        """Get project rules content."""
        if not self.is_in_project():
            return None

        ai_dir = self.ai_dir
        assert ai_dir is not None
        rules_path = ai_dir / "AGENTS.md"
        if not rules_path.exists():
            return None

        return rules_path.read_text()

    def add_skill(self, skill_name: str, skill_content: str) -> None:
        """Add a skill to the project."""
        if not self.is_in_project():
            raise ConfigError("Not in a project directory")

        skills_dir = self._require_ai_dir() / "skills"
        skills_dir.mkdir(exist_ok=True)

        skill_dir = skills_dir / skill_name
        skill_dir.mkdir(exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill_content)

    def enable_feature(self, feature: str) -> None:
        """Enable a feature for the project."""
        features = list(self.get_project_config().get("enabled_features", []))
        if feature not in features:
            features.append(feature)
        self.update_project_config({"enabled_features": features}, local=True)

    def disable_feature(self, feature: str) -> None:
        """Disable a feature for the project."""
        features = [
            f for f in self.get_project_config().get("enabled_features", []) if f != feature
        ]
        self.update_project_config({"enabled_features": features}, local=True)

    def get_mcp_config(self) -> Dict[str, Any]:
        """Get project MCP server configuration."""
        if not self.is_in_project():
            return {}

        mcp_config = {}

        # Load base MCP config
        ai_dir = self.ai_dir
        assert ai_dir is not None
        mcp_path = ai_dir / "mcp-config.json"
        if mcp_path.exists():
            try:
                mcp_config = load_json(mcp_path)
            except ConfigError:
                pass

        # Merge local overrides
        local_path = ai_dir / "mcp_config.local.json"
        if local_path.exists():
            try:
                local_config = load_json(local_path)
                mcp_config = deep_merge(mcp_config, local_config)
            except ConfigError:
                pass

        return mcp_config

    def save_mcp_config(self, config: Dict[str, Any], local: bool = False) -> None:
        """Save project MCP configuration."""
        if not self.is_in_project():
            raise ConfigError("Not in a project directory")

        config_path = self._require_ai_dir() / (
            "mcp-config.local.json" if local else "mcp-config.json"
        )
        save_json(config_path, config)

    def add_mcp_server(self, name: str, server_config: Dict[str, Any], local: bool = False) -> None:
        """Add an MCP server to the project."""
        if not self.is_in_project():
            raise ConfigError("Not in a project directory")

        mcp_config = self.get_mcp_config()

        if "mcpServers" not in mcp_config:
            mcp_config["mcpServers"] = {}

        mcp_config["mcpServers"][name] = server_config
        self.save_mcp_config(mcp_config, local=local)

"""
Environment management for universal AI configuration.
All agent-related data is consolidated under ~/.agents/
"""

import os
import platform
from pathlib import Path
from typing import List, Optional


class AgentEnv:
    """Manages the ~/.agents directory structure for AI agent configuration."""

    def __init__(self, app_name: str = "agent"):
        self.app_name = app_name
        self.home = Path.home()
        self.system = platform.system()

        # Base directory: ~/.agents (or user override)
        agent_base = os.getenv("AGENT_CONFIG_HOME")
        if agent_base:
            self.base = Path(agent_base)
        else:
            self.base = self.home / ".agents"

    @property
    def base_dir(self) -> Path:
        """Base agent directory."""
        return self.base

    @property
    def config(self) -> Path:
        """User configurations, prompts, and credentials."""
        return self.base / "config"

    @property
    def skills(self) -> Path:
        """Shared skills directory."""
        return self.base / "skills"

    @property
    def data(self) -> Path:
        """Persistent storage like long-term memory vector stores."""
        return self.base / "data"

    @property
    def state(self) -> Path:
        """Dynamic runtime data like chat history and logs."""
        return self.base / "state"

    @property
    def cache(self) -> Path:
        """Non-essential data like model caches and temporary embeddings."""
        return self.base / "cache"

    def project_config(self, cwd: Optional[Path] = None) -> Optional[Path]:
        """Project-local .ai/ directory from current working directory."""
        start = Path(cwd) if cwd else Path.cwd()

        # Walk up from cwd looking for .ai/ directory
        current = start
        while current != current.parent:
            ai_dir = current / ".ai"
            if ai_dir.exists():
                return ai_dir
            current = current.parent

        return None

    def initialize_dirs(self) -> List[Path]:
        """Creates the directory structure safely."""
        dirs = [self.base, self.config, self.skills, self.data, self.state, self.cache]
        created = []

        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)

        # Create subdirectories
        (self.data / "memory").mkdir(exist_ok=True)
        (self.data / "plugins").mkdir(exist_ok=True)
        (self.state / "logs").mkdir(exist_ok=True)
        (self.state / "history").mkdir(exist_ok=True)
        (self.cache / "models").mkdir(exist_ok=True)
        (self.cache / "venv").mkdir(exist_ok=True)

        return created

    def get_config_precedence(self, cwd: Optional[Path] = None) -> List[Path]:
        """Returns config paths in precedence order (highest to lowest)."""
        precedence = []

        # 1. Project local overrides
        project_dir = self.project_config(cwd)
        if project_dir:
            precedence.append(project_dir / "config.local.json")

        # 2. Project shared config
        if project_dir:
            precedence.append(project_dir / "config.json")

        # 3. User config
        precedence.append(self.config / "config.json")

        return [p for p in precedence if p.exists()]


def find_project_root(cwd: Optional[Path] = None) -> Optional[Path]:
    """Find project root by looking for .git, .jj, or .ai/ directory."""
    start = Path(cwd) if cwd else Path.cwd()
    current = start

    while current != current.parent:
        # Check for version control or .ai/ directory
        if (current / ".git").exists() or (current / ".jj").exists() or (current / ".ai").exists():
            return current
        current = current.parent

    return None

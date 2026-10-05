"""
Provider registry: where each AI tool keeps its config, MCP servers, rules,
and skills, plus how to translate the unified MCP format into each native shape.

Each spec has:
  detect_paths: existence of any path marks the provider as installed
  read_paths:   candidate locations scanned during migration
  user/project: sync targets for writing unified config back out
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class SyncTargets:
    """Native locations a provider reads at one scope (user or project)."""

    config_file: Optional[str] = None  # provider settings file
    mcp_file: Optional[str] = None  # file holding MCP servers (may equal config_file)
    mcp_key: Optional[str] = None  # key inside mcp_file holding the servers
    mcp_style: str = "map"  # map | vscode | zed | list
    rules_path: Optional[str] = None  # file or directory depending on rules_mode
    rules_mode: str = "none"  # file | mdc_dir | md_dir | none
    skills_dir: Optional[str] = None


@dataclass
class ProviderSpec:
    name: str
    display: str
    detect_paths: List[str]
    read_paths: Dict[str, List[str]]
    user: SyncTargets = field(default_factory=SyncTargets)
    project: SyncTargets = field(default_factory=SyncTargets)


def _vscode_user_dir() -> str:
    """Platform-specific VS Code user settings directory."""
    if sys.platform == "darwin":
        return "~/Library/Application Support/Code/User"
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", "~/AppData/Roaming"), "Code/User")
    return "~/.config/Code/User"


VSCODE_USER_DIR = _vscode_user_dir()

PROVIDERS: Dict[str, ProviderSpec] = {
    "devin": ProviderSpec(
        name="devin",
        display="Devin",
        detect_paths=["~/.config/devin", "~/.devin"],
        read_paths={
            "user_config": ["~/.config/devin/config.json"],
            "user_mcp": ["~/.config/devin/mcp_config.json"],
            "user_skills": ["~/.config/devin/skills/", "~/.devin/skills/"],
            "user_rules": ["~/.config/devin/AGENTS.md", "~/.devin/AGENTS.md"],
            "project_config": [".devin/config.json"],
            "project_mcp": [".devin/mcp_config.json"],
            "project_local": [".devin/config.local.json"],
            "project_local_mcp": [".devin/mcp_config.local.json"],
            "project_skills": [".devin/skills/"],
            "project_rules": ["AGENTS.md", ".devin/AGENTS.md"],
        },
        user=SyncTargets(
            config_file="~/.config/devin/config.json",
            mcp_file="~/.config/devin/mcp_config.json",
            mcp_key="mcpServers",
            rules_path="~/.config/devin/AGENTS.md",
            rules_mode="file",
            skills_dir="~/.config/devin/skills",
        ),
        project=SyncTargets(
            config_file=".devin/config.json",
            mcp_file=".devin/mcp_config.json",
            mcp_key="mcpServers",
            rules_path="AGENTS.md",
            rules_mode="file",
            skills_dir=".devin/skills",
        ),
    ),
    "windsurf": ProviderSpec(
        name="windsurf",
        display="Windsurf",
        detect_paths=["~/.codeium", "~/.windsurf"],
        read_paths={
            "user_config": [
                "~/.windsurf/config.json",
                "~/.windsurf/argv.json",
                "~/.codeium/config.json",
            ],
            "user_mcp": [
                "~/.codeium/mcp_config.json",
                "~/.windsurf/mcp_config.json",
                "~/.codeium/windsurf/mcp_config.json",
            ],
            "user_skills": ["~/.windsurf/skills/"],
            "user_rules": ["~/.codeium/windsurf/memories/global_rules.md", "~/.windsurf/AGENTS.md"],
            "project_config": [".windsurf/config.json"],
            "project_mcp": [".windsurf/mcp_config.json"],
            "project_local": [".windsurf/config.local.json"],
            "project_local_mcp": [".windsurf/mcp_config.local.json"],
            "project_skills": [".windsurf/skills/"],
            "project_rules": [".windsurf/rules/", ".windsurfrules"],
        },
        user=SyncTargets(
            config_file="~/.windsurf/config.json",
            mcp_file="~/.codeium/mcp_config.json",
            mcp_key="mcpServers",
            rules_path="~/.codeium/windsurf/memories/global_rules.md",
            rules_mode="file",
            skills_dir="~/.windsurf/skills",
        ),
        project=SyncTargets(
            config_file=".windsurf/config.json",
            mcp_file=".windsurf/mcp_config.json",
            mcp_key="mcpServers",
            rules_path=".windsurf/rules",
            rules_mode="md_dir",
            skills_dir=".windsurf/skills",
        ),
    ),
    "claude": ProviderSpec(
        name="claude",
        display="Claude",
        detect_paths=["~/.claude", "~/.claude.json"],
        read_paths={
            "user_config": ["~/.claude/settings.json", "~/.claude.json"],
            "user_mcp": ["~/.claude/mcp_config.json", "~/.claude.json"],
            "user_skills": ["~/.claude/skills/"],
            "user_rules": ["~/.claude/CLAUDE.md", "~/.claude/AGENTS.md"],
            "project_config": [".claude/settings.json", ".claude/config.json"],
            "project_mcp": [".mcp.json", ".claude/mcp_config.json"],
            "project_local": [".claude/settings.local.json", ".claude/config.local.json"],
            "project_local_mcp": [".claude/mcp_config.local.json"],
            "project_skills": [".claude/skills/"],
            "project_rules": ["CLAUDE.md", ".claude/CLAUDE.md"],
        },
        user=SyncTargets(
            config_file="~/.claude/settings.json",
            mcp_file="~/.claude/mcp_config.json",
            mcp_key="mcpServers",
            rules_path="~/.claude/CLAUDE.md",
            rules_mode="file",
            skills_dir="~/.claude/skills",
        ),
        project=SyncTargets(
            config_file=".claude/settings.json",
            mcp_file=".mcp.json",
            mcp_key="mcpServers",
            rules_path="CLAUDE.md",
            rules_mode="file",
            skills_dir=".claude/skills",
        ),
    ),
    "cursor": ProviderSpec(
        name="cursor",
        display="Cursor",
        detect_paths=["~/.cursor"],
        read_paths={
            "user_config": ["~/.cursor/settings.json"],
            "user_mcp": ["~/.cursor/mcp.json"],
            "user_skills": ["~/.cursor/skills/"],
            "user_rules": ["~/.cursor/rules/"],
            "project_config": [".cursor/settings.json"],
            "project_mcp": [".cursor/mcp.json"],
            "project_local": [".cursor/settings.local.json"],
            "project_local_mcp": [".cursor/mcp.local.json"],
            "project_skills": [".cursor/skills/"],
            "project_rules": [".cursor/rules/"],
        },
        user=SyncTargets(
            config_file="~/.cursor/settings.json",
            mcp_file="~/.cursor/mcp.json",
            mcp_key="mcpServers",
            rules_path="~/.cursor/rules",
            rules_mode="mdc_dir",
            skills_dir="~/.cursor/skills",
        ),
        project=SyncTargets(
            config_file=".cursor/settings.json",
            mcp_file=".cursor/mcp.json",
            mcp_key="mcpServers",
            rules_path=".cursor/rules",
            rules_mode="mdc_dir",
            skills_dir=".cursor/skills",
        ),
    ),
    "codex": ProviderSpec(
        name="codex",
        display="Codex CLI",
        detect_paths=["~/.codex"],
        read_paths={
            "user_config": ["~/.codex/config.toml"],
            "user_mcp": ["~/.codex/config.toml"],
            "user_rules": ["~/.codex/AGENTS.md"],
            "project_config": [".codex/config.toml"],
            "project_mcp": [".codex/config.toml"],
            "project_rules": ["AGENTS.md", "AGENTS.override.md"],
        },
        user=SyncTargets(
            config_file="~/.codex/config.toml",
            mcp_file="~/.codex/config.toml",
            mcp_key="mcp_servers",
            mcp_style="map",
            rules_path="~/.codex/AGENTS.md",
            rules_mode="file",
        ),
        project=SyncTargets(
            config_file=".codex/config.toml",
            mcp_file=".codex/config.toml",
            mcp_key="mcp_servers",
            mcp_style="map",
            rules_path="AGENTS.md",
            rules_mode="file",
        ),
    ),
    "gemini": ProviderSpec(
        name="gemini",
        display="Gemini CLI",
        detect_paths=["~/.gemini"],
        read_paths={
            "user_config": ["~/.gemini/settings.json"],
            "user_mcp": ["~/.gemini/settings.json"],
            "user_rules": ["~/.gemini/GEMINI.md"],
            "project_config": [".gemini/settings.json"],
            "project_mcp": [".gemini/settings.json"],
            "project_rules": ["GEMINI.md"],
        },
        user=SyncTargets(
            config_file="~/.gemini/settings.json",
            mcp_file="~/.gemini/settings.json",
            mcp_key="mcpServers",
            rules_path="~/.gemini/GEMINI.md",
            rules_mode="file",
        ),
        project=SyncTargets(
            config_file=".gemini/settings.json",
            mcp_file=".gemini/settings.json",
            mcp_key="mcpServers",
            rules_path="GEMINI.md",
            rules_mode="file",
        ),
    ),
    "vscode": ProviderSpec(
        name="vscode",
        display="VS Code",
        detect_paths=[VSCODE_USER_DIR, "~/.vscode"],
        read_paths={
            "user_config": [f"{VSCODE_USER_DIR}/settings.json"],
            "user_mcp": [f"{VSCODE_USER_DIR}/mcp.json"],
            "project_config": [".vscode/settings.json"],
            "project_mcp": [".vscode/mcp.json"],
            "project_rules": [".github/copilot-instructions.md"],
        },
        user=SyncTargets(
            config_file=f"{VSCODE_USER_DIR}/settings.json",
            mcp_file=f"{VSCODE_USER_DIR}/mcp.json",
            mcp_key="servers",
            mcp_style="vscode",
        ),
        project=SyncTargets(
            config_file=".vscode/settings.json",
            mcp_file=".vscode/mcp.json",
            mcp_key="servers",
            mcp_style="vscode",
            rules_path=".github/copilot-instructions.md",
            rules_mode="file",
        ),
    ),
    "copilot": ProviderSpec(
        name="copilot",
        display="GitHub Copilot CLI",
        detect_paths=["~/.copilot"],
        read_paths={
            "user_config": ["~/.copilot/settings.json"],
            "user_mcp": ["~/.copilot/mcp-config.json"],
            "user_rules": ["~/.copilot/copilot-instructions.md"],
            "project_config": [],
            "project_mcp": [".mcp.json", ".github/mcp.json"],
            "project_rules": [".github/copilot-instructions.md"],
        },
        user=SyncTargets(
            config_file="~/.copilot/settings.json",
            mcp_file="~/.copilot/mcp-config.json",
            mcp_key="mcpServers",
            mcp_style="map",
            rules_path="~/.copilot/copilot-instructions.md",
            rules_mode="file",
            skills_dir="~/.copilot/skills",
        ),
        project=SyncTargets(
            mcp_file=".mcp.json",
            mcp_key="mcpServers",
            mcp_style="map",
            rules_path=".github/copilot-instructions.md",
            rules_mode="file",
        ),
    ),
    "zed": ProviderSpec(
        name="zed",
        display="Zed",
        detect_paths=["~/.config/zed", "~/.zed"],
        read_paths={
            "user_config": ["~/.config/zed/settings.json"],
            "user_mcp": ["~/.config/zed/settings.json"],
            "project_config": [".zed/settings.json"],
            "project_mcp": [".zed/settings.json"],
            "project_rules": [".rules", "AGENTS.md"],
        },
        user=SyncTargets(
            config_file="~/.config/zed/settings.json",
            mcp_file="~/.config/zed/settings.json",
            mcp_key="context_servers",
            mcp_style="zed",
        ),
        project=SyncTargets(
            config_file=".zed/settings.json",
            mcp_file=".zed/settings.json",
            mcp_key="context_servers",
            mcp_style="zed",
            rules_path=".rules",
            rules_mode="file",
        ),
    ),
    "continue": ProviderSpec(
        name="continue",
        display="Continue",
        detect_paths=["~/.continue"],
        read_paths={
            "user_config": [
                "~/.continue/config.yaml",
                "~/.continue/config.yml",
                "~/.continue/config.json",
            ],
            "user_mcp": [
                "~/.continue/config.yaml",
                "~/.continue/config.yml",
                "~/.continue/config.json",
            ],
            "user_rules": ["~/.continue/rules/"],
            "project_config": [".continue/config.yaml", ".continue/config.json"],
            "project_mcp": [".continue/config.yaml", ".continue/config.json"],
            "project_rules": [".continue/rules/"],
        },
        user=SyncTargets(
            config_file="~/.continue/config.yaml",
            mcp_file="~/.continue/config.yaml",
            mcp_key="mcpServers",
            mcp_style="list",
            rules_path="~/.continue/rules",
            rules_mode="md_dir",
        ),
        project=SyncTargets(
            config_file=".continue/config.yaml",
            mcp_file=".continue/config.yaml",
            mcp_key="mcpServers",
            mcp_style="list",
            rules_path=".continue/rules",
            rules_mode="md_dir",
        ),
    ),
}


def expand(path: str) -> Path:
    return Path(path).expanduser()


def detect_installed() -> List[str]:
    """Providers whose native directories/files already exist."""
    installed = []
    for name, spec in PROVIDERS.items():
        if any(expand(p).exists() for p in spec.detect_paths):
            installed.append(name)
    return installed


def render_mcp_servers(style: str, servers: Dict[str, Any]) -> Any:
    """Translate unified mcpServers into a provider-native value.

    Unified shape per server: {"command": str, "args": [...], "env": {...}}
    or remote: {"url": str, "headers": {...}}.
    """
    if style == "vscode":
        out = {}
        for name, srv in servers.items():
            if not isinstance(srv, dict):
                continue
            entry = dict(srv)
            entry["type"] = "http" if "url" in srv else "stdio"
            out[name] = entry
        return out

    if style == "zed":
        out = {}
        for name, srv in servers.items():
            if not isinstance(srv, dict) or "command" not in srv:
                continue  # Zed only supports local stdio servers in settings.json
            out[name] = {
                "command": {
                    "path": srv.get("command"),
                    "args": srv.get("args", []),
                    "env": srv.get("env", {}),
                },
                "settings": srv.get("settings", {}),
            }
        return out

    if style == "list":
        return [{"name": name, **srv} for name, srv in servers.items() if isinstance(srv, dict)]

    # "map": standard mcpServers / mcp_servers shape, passed through
    return dict(servers)


def normalize_mcp_server(srv: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty containers so equivalent server configs compare equal.

    Native translations may inject empty fields (e.g. zed's env: {}); those
    should not count as differences against the unified entry.
    """
    return {k: v for k, v in srv.items() if v is not None and v != {} and v != [] and v != ""}


def normalize_mcp_name(name: str) -> str:
    """Reduce an MCP server name to a comparable form.

    Providers use different naming schemes for the same server, e.g.
    VS Code registry names: io.github.X/chrome-devtools-mcp,
    microsoft/playwright-mcp. Returns basename lowercased with common
    mcp/server affixes stripped.
    """
    base = name.rsplit("/", 1)[-1].lower().replace("_", "-")
    if base.startswith("mcp-"):
        base = base[4:]
    for suffix in ("-mcp-server", "-mcp", "-server"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base or name.lower()


def extract_mcp_servers(spec: ProviderSpec, data: Dict[str, Any]) -> Dict[str, Any]:
    """Pull MCP servers out of a loaded provider config, normalized to the
    unified mcpServers map shape."""
    if not data:
        return {}

    key = spec.user.mcp_key or "mcpServers"
    raw = data.get(key)

    # Fall back to the conventional key if the provider-native one is absent
    if raw is None:
        raw = data.get("mcpServers")
    if raw is None:
        return {}

    style = spec.user.mcp_style
    if style == "list" and isinstance(raw, list):
        return {
            item["name"]: normalize_mcp_server({k: v for k, v in item.items() if k != "name"})
            for item in raw
            if isinstance(item, dict) and "name" in item
        }
    if style == "zed" and isinstance(raw, dict):
        out = {}
        for name, srv in raw.items():
            if isinstance(srv, dict) and "command" in srv:
                cmd = srv["command"]
                out[name] = normalize_mcp_server(
                    {
                        "command": cmd.get("path"),
                        "args": cmd.get("args", []),
                        "env": cmd.get("env", {}),
                    }
                )
        return out
    if style == "vscode" and isinstance(raw, dict):
        out = {}
        for name, srv in raw.items():
            if isinstance(srv, dict):
                out[name] = normalize_mcp_server({k: v for k, v in srv.items() if k != "type"})
        return out

    if isinstance(raw, dict):
        return {
            name: normalize_mcp_server(srv) for name, srv in raw.items() if isinstance(srv, dict)
        }
    return {}

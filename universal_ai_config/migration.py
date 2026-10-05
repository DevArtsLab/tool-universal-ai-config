"""
Migration logic for existing AI provider configurations.
Discovers and migrates configs, MCP servers, skills, and rules from provider-specific paths.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from .config import UnifiedConfig, deep_merge, load_json, save_json, ConfigError
from .environment import AgentEnv
from .formats import load_any_safe
from .providers import PROVIDERS, extract_mcp_servers


class MigrationError(Exception):
    """Migration-related errors."""

    pass


class ProviderMigrator:
    """Handles migration from provider-specific configs to unified config."""

    # Known provider config locations to scan (from the provider registry)
    PROVIDER_PATHS = {name: spec.read_paths for name, spec in PROVIDERS.items()}

    def __init__(self, env: Optional[AgentEnv] = None):
        self.env = env or AgentEnv()
        self.config = UnifiedConfig(env)

    def _find_first_existing(self, paths: List[str]) -> Optional[Path]:
        """Find the first existing path from a list of candidates."""
        for path_str in paths:
            path = Path(path_str).expanduser()
            if path.exists():
                return path
        return None

    def get_legacy_path(self, provider: str, key: str = "user_config") -> Optional[Path]:
        """Get legacy path for a provider."""
        if provider not in self.PROVIDER_PATHS:
            return None

        paths = self.PROVIDER_PATHS[provider].get(key, [])
        return self._find_first_existing(paths)

    def detect_providers(self) -> List[str]:
        """Detect which providers have legacy configs."""
        detected = []

        for provider in self.PROVIDER_PATHS.keys():
            if self.get_legacy_path(provider, "user_config"):
                detected.append(provider)
            elif self.get_legacy_path(provider, "user_mcp"):
                detected.append(provider)
            elif self.get_legacy_path(provider, "user_skills"):
                detected.append(provider)

        return list(set(detected))

    def _load_json_safe(self, path: Optional[Path]) -> Optional[Dict[str, Any]]:
        """Load JSON file safely, returning None on error."""
        if not path or not path.exists():
            return None
        data = load_any_safe(path)
        return data if data else None

    def migrate_provider(self, provider: str) -> Dict[str, Any]:
        """Migrate a single provider to unified config."""
        if provider not in self.PROVIDER_PATHS:
            raise MigrationError(f"Unknown provider: {provider}")

        legacy_path = self.get_legacy_path(provider, "user_config")
        if not legacy_path:
            # Provider may have only MCP or skills
            legacy_path = self.get_legacy_path(provider, "user_mcp") or self.get_legacy_path(
                provider, "user_skills"
            )

        if not legacy_path:
            raise MigrationError(f"No legacy config found for {provider}")

        print(f"Migrating {provider} from {legacy_path}")

        # Load legacy config
        legacy_config = self._load_json_safe(self.get_legacy_path(provider, "user_config")) or {}

        # Transform to unified format
        provider_settings = self._transform_config(provider, legacy_config)

        # Update unified config
        if provider_settings:
            self.config.update_provider(provider, provider_settings)

        # Migrate MCP servers (from config file and/or dedicated MCP file)
        spec = PROVIDERS[provider]
        mcp_sources = []
        config_src = self.get_legacy_path(provider, "user_config")
        if config_src:
            mcp_sources.append((config_src, False))
        mcp_src = self.get_legacy_path(provider, "user_mcp")
        if mcp_src and mcp_src != config_src:
            mcp_sources.append((mcp_src, True))

        for src, allow_root_level in mcp_sources:
            data = load_any_safe(src)
            servers = extract_mcp_servers(spec, data)
            if not servers and allow_root_level and data:
                # Some MCP files hold servers at the root level
                servers = {
                    k: v
                    for k, v in data.items()
                    if isinstance(v, dict) and ("command" in v or "url" in v)
                }
            for name, server_config in servers.items():
                self.config.add_mcp_server(name, server_config)
                print(f"  Migrated MCP server from {src}: {name}")

        # Migrate skills directory
        self._migrate_skills(provider)

        # Migrate rules file
        self._migrate_rules(provider)

        # Backup legacy config (only if it's a config file, not a directory)
        config_path = self.get_legacy_path(provider, "user_config")
        if config_path and config_path.is_file():
            backup_path = config_path.with_suffix(".json.backup")
            if not backup_path.exists():
                shutil.copy2(config_path, backup_path)
                print(f"  Backed up legacy config to: {backup_path}")

        return provider_settings

    def _transform_config(self, provider: str, legacy_config: Dict[str, Any]) -> Dict[str, Any]:
        """Transform provider-specific config to unified format."""
        settings = {}

        # Common fields that might exist across providers
        if "agent" in legacy_config:
            settings["model"] = legacy_config["agent"].get("model")

        if "permissions" in legacy_config:
            settings["permissions"] = legacy_config["permissions"]

        if "theme_mode" in legacy_config:
            settings["theme_mode"] = legacy_config["theme_mode"]

        # Provider-specific transformations
        if provider == "devin":
            if "show_history_on_continue" in legacy_config.get("agent", {}):
                settings["show_history_on_continue"] = legacy_config["agent"][
                    "show_history_on_continue"
                ]

        elif provider == "claude":
            # Claude settings.json may have different structure
            if "model" in legacy_config:
                settings["model"] = legacy_config["model"]

        return settings

    def _migrate_skills(self, provider: str) -> None:
        """Migrate skills directory for a provider."""
        legacy_skills = self.get_legacy_path(provider, "user_skills")
        if not legacy_skills or not legacy_skills.exists():
            return

        unified_skills = self.env.skills
        unified_skills.mkdir(parents=True, exist_ok=True)

        # Copy skills to unified location
        migrated = 0
        for skill_file in legacy_skills.rglob("SKILL.md"):
            skill_name = skill_file.parent.name
            target_dir = unified_skills / skill_name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, target_dir / "SKILL.md")
            print(f"  Migrated skill: {skill_name}")
            migrated += 1

        # Also migrate loose .md files as skills
        for skill_file in legacy_skills.glob("*.md"):
            if skill_file.name == "SKILL.md":
                continue
            skill_name = skill_file.stem
            target_dir = unified_skills / skill_name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, target_dir / "SKILL.md")
            print(f"  Migrated skill: {skill_name}")
            migrated += 1

        if migrated == 0:
            print(f"  No skills found in {legacy_skills}")

    def _read_rules_source(self, path: Path) -> str:
        """Read rules text from a file or a directory of rule files."""
        if path.is_dir():
            parts = []
            for f in sorted(path.rglob("*")):
                if f.is_file() and f.suffix in (".md", ".mdc", ".rules"):
                    parts.append(f.read_text())
            return "\n\n".join(parts)
        return path.read_text()

    def _migrate_rules(self, provider: str) -> None:
        """Migrate rules file for a provider."""
        legacy_rules = self.get_legacy_path(provider, "user_rules")
        if not legacy_rules or not legacy_rules.exists():
            return

        unified_rules = self.env.config / "AGENTS.md"
        unified_rules.parent.mkdir(parents=True, exist_ok=True)

        if not unified_rules.exists():
            unified_rules.write_text(self._read_rules_source(legacy_rules))
            print(f"  Migrated rules to: {unified_rules}")
        else:
            # Append to existing rules
            existing = unified_rules.read_text()
            additional = self._read_rules_source(legacy_rules)
            unified_rules.write_text(
                f"{existing}\n\n<!-- Migrated from {provider} -->\n{additional}"
            )
            print(f"  Appended rules from: {legacy_rules}")

    def migrate_all(self) -> Dict[str, Any]:
        """Migrate all detected providers."""
        detected = self.detect_providers()

        if not detected:
            print("No legacy configs found")
            return {}

        print(f"Detected providers: {', '.join(detected)}")

        results: Dict[str, Optional[Dict[str, Any]]] = {}
        for provider in detected:
            try:
                results[provider] = self.migrate_provider(provider)
            except MigrationError as e:
                print(f"Failed to migrate {provider}: {e}")
                results[provider] = None

        return results

    def migrate_project(self, project_root: Path) -> None:
        """Migrate project-specific configs."""
        ai_dir = project_root / ".ai"
        ai_dir.mkdir(exist_ok=True)

        for provider in self.PROVIDER_PATHS.keys():
            # Migrate project config
            project_config = self.get_legacy_path(provider, "project_config")
            if project_config and project_config.exists():
                try:
                    legacy_config = self._load_json_safe(project_config)
                    if legacy_config:
                        project_unified = ai_dir / "config.json"

                        if project_unified.exists():
                            existing = load_json(project_unified)
                            merged = deep_merge(existing, legacy_config)
                        else:
                            merged = legacy_config

                        save_json(project_unified, merged)
                        print(f"Migrated {provider} project config to {project_unified}")
                except ConfigError:
                    pass

            # Migrate project MCP config
            project_mcp = self.get_legacy_path(provider, "project_mcp")
            if project_mcp and project_mcp.exists() and project_mcp.is_file():
                try:
                    legacy_config = self._load_json_safe(project_mcp)
                    if legacy_config:
                        spec = PROVIDERS[provider]
                        servers = extract_mcp_servers(spec, legacy_config)
                        if servers:
                            legacy_config = {"mcpServers": servers}
                    if legacy_config and "mcpServers" in legacy_config:
                        project_mcp_unified = ai_dir / "mcp-config.json"

                        if project_mcp_unified.exists():
                            existing = load_json(project_mcp_unified)
                            merged_mcp = existing
                            merged_mcp["mcpServers"] = deep_merge(
                                existing.get("mcpServers", {}), legacy_config["mcpServers"]
                            )
                        else:
                            merged_mcp = legacy_config

                        save_json(project_mcp_unified, merged_mcp)
                        print(f"Migrated {provider} project MCP config to {project_mcp_unified}")
                except ConfigError:
                    pass

            # Migrate project local config
            project_local = self.get_legacy_path(provider, "project_local")
            if project_local and project_local.exists():
                try:
                    legacy_config = self._load_json_safe(project_local)
                    if legacy_config:
                        project_local_unified = ai_dir / "config.local.json"

                        if project_local_unified.exists():
                            existing = load_json(project_local_unified)
                            merged = deep_merge(existing, legacy_config)
                        else:
                            merged = legacy_config

                        save_json(project_local_unified, merged)
                        print(
                            f"Migrated {provider} project local config to {project_local_unified}"
                        )
                except ConfigError:
                    pass

            # Migrate project skills
            project_skills = self.get_legacy_path(provider, "project_skills")
            if project_skills and project_skills.exists():
                unified_skills = ai_dir / "skills"
                unified_skills.mkdir(exist_ok=True)

                for skill_file in project_skills.rglob("SKILL.md"):
                    skill_name = skill_file.parent.name
                    target_dir = unified_skills / skill_name
                    target_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(skill_file, target_dir / "SKILL.md")
                    print(f"Migrated {provider} project skill: {skill_name}")

            # Migrate project rules
            project_rules = self._find_first_existing(
                [
                    str(project_root / p)
                    for p in self.PROVIDER_PATHS[provider].get("project_rules", [])
                ]
            )
            if project_rules and project_rules.exists():
                unified_rules = ai_dir / "AGENTS.md"
                if not unified_rules.exists():
                    unified_rules.write_text(self._read_rules_source(project_rules))
                    print(f"Migrated {provider} project rules to {unified_rules}")

    def _copy_skills_to_global(self, skills_dir: Path, source_label: str = "") -> int:
        """Copy all skills from a directory to the global ~/.agents/skills location."""
        if not skills_dir or not skills_dir.exists():
            return 0

        unified_skills = self.env.skills
        unified_skills.mkdir(parents=True, exist_ok=True)

        migrated = 0
        prefix = f"{source_label}: " if source_label else ""

        # Copy structured skills (SKILL.md in subdirectories)
        for skill_file in skills_dir.rglob("SKILL.md"):
            skill_name = skill_file.parent.name
            target_dir = unified_skills / skill_name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, target_dir / "SKILL.md")
            print(f"  {prefix}Migrated skill: {skill_name}")
            migrated += 1

        # Also migrate loose .md files as skills
        for skill_file in skills_dir.glob("*.md"):
            if skill_file.name == "SKILL.md":
                continue
            skill_name = skill_file.stem
            target_dir = unified_skills / skill_name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, target_dir / "SKILL.md")
            print(f"  {prefix}Migrated skill: {skill_name}")
            migrated += 1

        return migrated

    def find_project_skill_dirs(
        self, search_paths: Optional[List[Path]] = None, max_depth: int = 3
    ) -> List[Path]:
        """Find all project skill directories under search paths.

        Searches up to max_depth levels below each search path to avoid
        crawling the entire home directory.
        """
        if search_paths is None:
            search_paths = [Path.home() / "projects", Path.home()]

        skill_patterns = []
        for provider in self.PROVIDER_PATHS.values():
            for pattern in provider.get("project_skills", []):
                skill_patterns.append(Path(pattern))

        skill_dirs = []
        for base in search_paths:
            if not base.exists():
                continue
            for skill_pattern in skill_patterns:
                # Build depth-limited glob patterns
                for depth in range(1, max_depth + 1):
                    glob_pattern = "/".join(["*"] * depth) + "/" + str(skill_pattern)
                    for path in base.glob(glob_pattern):
                        if path.is_dir():
                            skill_dirs.append(path)

        return sorted(set(skill_dirs))

    def migrate_all_project_skills(self, search_paths: Optional[List[Path]] = None) -> int:
        """Scan all projects and migrate their skills to global ~/.agents/skills."""
        skill_dirs = self.find_project_skill_dirs(search_paths)

        if not skill_dirs:
            print("No project skill directories found")
            return 0

        print(
            f"Found {len(skill_dirs)} project skill director{'y' if len(skill_dirs) == 1 else 'ies'}:"
        )
        for skill_dir in skill_dirs:
            print(f"  - {skill_dir}")

        total = 0
        for skill_dir in skill_dirs:
            label = str(skill_dir.relative_to(Path.home()))
            count = self._copy_skills_to_global(skill_dir, source_label=label)
            total += count

        print(f"\nMigrated {total} project skill(s) to {self.env.skills}")
        return total

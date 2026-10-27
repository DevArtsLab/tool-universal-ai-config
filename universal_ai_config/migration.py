"""
Migration logic for existing AI provider configurations.
Discovers and migrates configs, MCP servers, skills, and rules from provider-specific paths.
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from .config import UnifiedConfig, deep_merge, load_json, save_json, ConfigError
from .environment import AgentEnv
from .formats import load_any_safe
from .providers import (
    PROVIDERS,
    extract_mcp_servers,
    normalize_mcp_name,
    normalize_mcp_server,
)
from .lockfile import SkillsLock, dir_hash, skill_files
from .sync import _SKILL_ALIAS_RE, dirs_equal, strip_managed_markers


class MigrationError(Exception):
    """Migration-related errors."""

    pass


# Same-name skills with different content are quarantined here, one level
# outside the skills dir, so providers never discover a folder whose name
# does not match its SKILL.md frontmatter. Aliases like '<name>.claude'
# inside the skills dir create exactly that broken shape; conflicts live
# outside the store until the user resolves them.
SKILL_CONFLICTS_DIR = "skill-conflicts"

_FRONTMATTER_NAME_RE = re.compile(r"^name:\s*(\S+)", re.M)


def _skill_frontmatter_name(skill_md: Path) -> Optional[str]:
    """The 'name:' declared inside a SKILL.md, if present."""
    try:
        m = _FRONTMATTER_NAME_RE.search(skill_md.read_text(errors="replace"))
    except OSError:
        return None
    return m.group(1) if m else None


class ProviderMigrator:
    """Handles migration from provider-specific configs to unified config."""

    # Known provider config locations to scan (from the provider registry)
    PROVIDER_PATHS = {name: spec.read_paths for name, spec in PROVIDERS.items()}

    def __init__(self, env: Optional[AgentEnv] = None, interactive: Optional[bool] = None):
        self.env = env or AgentEnv()
        self.config = UnifiedConfig(env)
        # None: prompt when stdin is a TTY, quarantine silently otherwise.
        self.interactive = sys.stdin.isatty() if interactive is None else interactive

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

    def _find_project_path(self, provider: str, key: str, project_root: Path) -> Optional[Path]:
        """First existing read-path for a project key, resolved against
        project_root - provider project patterns like '.claude/skills' are
        relative and must not depend on the caller's CWD."""
        for pattern in self.PROVIDER_PATHS.get(provider, {}).get(key, []):
            candidate = Path(pattern)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            else:
                candidate = candidate.expanduser()
            if candidate.exists():
                return candidate
        return None

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

    @staticmethod
    def _find_equivalent(
        name: str, server_config: Dict[str, Any], existing: Dict[str, Any]
    ) -> Optional[str]:
        """Return the key of an existing entry that represents the same server.

        Exact name match first, then normalized-name match so provider registry
        names like io.github.X/foo-mcp match a unified 'foo'. Empty-field-only
        differences (env: {}) are ignored.
        """
        if name in existing:
            return name
        norm = normalize_mcp_name(name)
        for ename in existing:
            if normalize_mcp_name(ename) == norm:
                return ename
        return None

    @staticmethod
    def _is_name_conflict(name: str, match: str) -> bool:
        """True only when the incoming name literally collides."""
        return name == match

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

        existing_servers = self.config.load_mcp_servers()
        provider_server_names: List[str] = []
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
                server_config = normalize_mcp_server(server_config)
                match = self._find_equivalent(name, server_config, existing_servers)
                if match and normalize_mcp_server(existing_servers[match]) == server_config:
                    print(f"  Skipping duplicate MCP server: {name}")
                    provider_server_names.append(match)
                    continue
                if match and self._is_name_conflict(name, match):
                    # Exact name collision with different config: find or mint
                    # an alias. Reuse an existing alias whose config already
                    # matches so re-migrating does not mint .2, .3, ...
                    alias = f"{name}.{provider}"
                    n = 2
                    while (
                        alias in existing_servers
                        and normalize_mcp_server(existing_servers[alias]) != server_config
                    ):
                        alias = f"{name}.{provider}.{n}"
                        n += 1
                    if alias in existing_servers:
                        print(f"  Skipping duplicate MCP server: {name} (as {alias})")
                        provider_server_names.append(alias)
                        continue
                    print(
                        f"  MCP server '{name}' differs from existing "
                        f"'{match}'; kept as '{alias}'"
                    )
                    name = alias
                elif match:
                    # Similar normalized name, distinct config, unique name:
                    # import as-is and note the near-duplicate
                    print(
                        f"  Note: '{name}' looks similar to '{match}' "
                        f"but has a different config"
                    )
                self.config.add_mcp_server(name, server_config)
                existing_servers[name] = server_config
                provider_server_names.append(name)
                print(f"  Migrated MCP server from {src}: {name}")

        # Seed providers.<name>.mcp.include with the names the provider
        # actually had (post-dedupe/alias names). Sync export is fail-closed,
        # so the provider keeps its own set and unified additions need
        # explicit opt-in. A hand-set scope is never clobbered.
        if provider_server_names:
            prov_conf = (
                self.config.load_unified(include_mcp=False).get("providers", {}).get(provider, {})
            )
            if not isinstance(prov_conf.get("mcp"), dict):
                seeded = sorted(set(provider_server_names))
                self.config.update_provider(provider, {"mcp": {"include": seeded}})
                print(f"  Scoped providers.{provider}.mcp.include: {len(seeded)} server(s)")

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

        migrated = self._import_skills_dir(legacy_skills, self.env.skills, provider)
        if migrated == 0:
            print(f"  No new skills found in {legacy_skills}")

    def _import_skills_dir(self, src_dir: Path, target_root: Path, provider: str) -> int:
        """Copy skills into target_root: identical and strictly-subset skills
        are skipped, a conflicting same-name skill is quarantined under
        skill-conflicts/<name>/<provider>/, and the whole skill directory is
        copied so companion files (references/, scripts/) survive the move."""
        target_root.mkdir(parents=True, exist_ok=True)
        migrated = 0
        lock = SkillsLock(target_root.parent)
        # Depth-1 only: a SKILL.md nested inside a skill's own companion dirs
        # is part of that skill, not a separate top-level skill.
        for skill_file in sorted(src_dir.glob("*/SKILL.md")):
            # Dot-dirs (.ai-config-backups/, .<name>.ai-config-staged) are
            # tool internals, never skills.
            if skill_file.parent.name.startswith("."):
                continue
            migrated += self._import_one_skill(skill_file.parent, target_root, provider, lock)
        for skill_file in sorted(src_dir.glob("*.md")):
            if skill_file.name != "SKILL.md":
                migrated += self._import_one_loose_skill(skill_file, target_root, provider, lock)
        if lock.data["skills"] or lock.data["conflicts"]:
            lock.save()
        return migrated

    def _import_one_skill(
        self, skill_dir: Path, target_root: Path, provider: str, lock: SkillsLock
    ) -> int:
        name = skill_dir.name
        target = target_root / name
        if target.is_dir():
            if dirs_equal(skill_dir, target):
                print(f"  Skipping duplicate skill: {name}")
                return 0
            if self._is_subset(skill_dir, target):
                print(f"  Skipping subset skill: {name} ({provider} adds nothing)")
                return 0
            return self._resolve_skill_conflict(
                name,
                incoming=skill_dir,
                existing=target,
                target_root=target_root,
                provider=provider,
                lock=lock,
            )
        self._move_stray_aside(target_root, name, target)
        try:
            shutil.copytree(skill_dir, target)
        except (OSError, shutil.Error) as e:
            print(f"  Failed to migrate skill {name}: {e}")
            return 0
        lock.record_source(target.name, dir_hash(target), origin=f"imported:{provider}")
        print(f"  Migrated skill: {target.name}")
        return 1

    def _move_stray_aside(self, target_root: Path, name: str, target: Path) -> None:
        """A non-directory (or broken symlink) sitting at a skill's path
        blocks the import: park it in skill-conflicts/ rather than deleting
        or crashing on it."""
        if not target.is_symlink() and not target.exists():
            return
        if target.is_dir() and not target.is_symlink():
            return
        stray = self._conflict_dir(target_root, name, "stray")
        stray.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(stray))
        print(f"  Moved stray file aside: {target} -> {stray}")

    @staticmethod
    def _is_subset(incoming: Path, existing: Path) -> bool:
        """True when every content file in incoming exists in existing with
        identical bytes: a thinner provider copy adds nothing and is a
        duplicate, not a conflict."""
        inc = skill_files(incoming)
        ext = skill_files(existing)
        return all(rel in ext and ext[rel].read_bytes() == p.read_bytes() for rel, p in inc.items())

    def _conflict_dir(self, target_root: Path, name: str, tag: str) -> Path:
        """First free quarantine path for a conflicting skill."""
        conflicts = target_root.parent / SKILL_CONFLICTS_DIR / name
        dest = conflicts / tag
        n = 2
        while dest.exists():
            dest = conflicts / f"{tag}.{n}"
            n += 1
        return dest

    def _resolve_skill_conflict(
        self,
        name: str,
        incoming: Path,
        existing: Path,
        target_root: Path,
        provider: str,
        lock: SkillsLock,
    ) -> int:
        """Same skill name, different content: never mint a '<name>.<provider>'
        folder inside the skills store (its frontmatter name would no longer
        match the folder name, breaking the skill). Default: quarantine the
        incoming copy under skill-conflicts/ and keep the existing one; on a
        TTY, ask which copy to hold. Returns skills imported (0 or 1)."""
        existing_fm = _skill_frontmatter_name(existing / "SKILL.md")
        incoming_fm = _skill_frontmatter_name(incoming / "SKILL.md")
        print(f"  Skill conflict: '{name}'")
        print(f"    existing: {existing} (frontmatter name: {existing_fm})")
        print(f"    incoming: {incoming} (frontmatter name: {incoming_fm})")

        choice = "keep"
        if self.interactive:
            answer = (
                input(
                    f"    Hold which copy? [k]eep existing / [r]eplace with "
                    f"{provider} copy / [s]kip (default: k): "
                )
                .strip()
                .lower()
            )
            if answer in ("r", "replace"):
                choice = "replace"
            elif answer in ("s", "skip"):
                choice = "skip"

        if choice == "skip":
            print(f"    Skipped {name} from {provider}; left unresolved")
            lock.record_conflict(name, provider, None, resolution="skipped")
            return 0

        loser = self._conflict_dir(target_root, name, provider)
        loser.parent.mkdir(parents=True, exist_ok=True)
        if choice == "replace":
            displaced = self._conflict_dir(target_root, name, "unified")
            displaced.parent.mkdir(parents=True, exist_ok=True)
            # Stage the incoming copy beside the store first, then swap: a
            # copy failure must never leave the store without the skill.
            staged = target_root / f".{name}.ai-config-staged"
            try:
                if staged.exists():
                    shutil.rmtree(staged)
                shutil.copytree(incoming, staged)
                shutil.move(str(existing), str(displaced))
                staged.rename(existing)
            except (OSError, shutil.Error) as e:
                if staged.exists():
                    shutil.rmtree(staged, ignore_errors=True)
                if not existing.exists() and displaced.exists():
                    shutil.move(str(displaced), str(existing))
                print(f"    Replace failed ({e}); kept existing")
                return 0
            lock.record_source(name, dir_hash(existing), origin=f"imported:{provider}")
            lock.record_conflict(
                name, provider, str(displaced), resolution=f"replaced-by-{provider}"
            )
            print(f"    Replaced with {provider} copy; previous held at {displaced}")
            return 1

        # Copy, not move: the provider's own skills dir keeps its copy.
        try:
            shutil.copytree(incoming, loser)
        except (OSError, shutil.Error) as e:
            print(f"    Quarantine failed ({e}); {name} left in place")
            return 0
        lock.record_conflict(name, provider, str(loser), resolution="kept-existing")
        print(f"    Kept existing; {provider} copy held at {loser}")
        print(f"    Resolve with: compare {loser} to {existing}, then remove the loser")
        return 0

    def _import_one_loose_skill(
        self, skill_file: Path, target_root: Path, provider: str, lock: SkillsLock
    ) -> int:
        name = skill_file.stem
        target = target_root / name / "SKILL.md"
        if target.exists():
            if target.read_bytes() == skill_file.read_bytes():
                print(f"  Skipping duplicate skill: {name}")
                return 0
            # Stage the loose file as a dir-shaped skill and run the same
            # conflict policy as directory skills.
            with tempfile.TemporaryDirectory() as tmp:
                staged = Path(tmp) / name
                staged.mkdir()
                shutil.copy2(skill_file, staged / "SKILL.md")
                return self._resolve_skill_conflict(
                    name,
                    incoming=staged,
                    existing=target.parent,
                    target_root=target_root,
                    provider=provider,
                    lock=lock,
                )
        self._move_stray_aside(target_root, name, target.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(skill_file, target)
        except OSError as e:
            print(f"  Failed to migrate skill {name}: {e}")
            return 0
        lock.record_source(
            target.parent.name, dir_hash(target.parent), origin=f"imported:{provider}"
        )
        print(f"  Migrated skill: {target.parent.name}")
        return 1

    def reconcile_skill_aliases(self, skills_dir: Path) -> int:
        """Move legacy '<name>.<provider>' alias dirs out of the skills store
        into skill-conflicts/<name>/<provider>/, preserving all content. Alias
        folders break the skill rule that the folder name equal the SKILL.md
        frontmatter name, so they can never load as skills anyway."""
        moved = 0
        lock = SkillsLock(skills_dir.parent)
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir():
                continue
            m = _SKILL_ALIAS_RE.match(d.name)
            if not m:
                continue
            base = m.group("base")
            provider_tag = m.group("provider")
            dest = self._conflict_dir(skills_dir, base, provider_tag)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(dest))
            lock.record_conflict(base, provider_tag, str(dest), resolution="alias-reconciled")
            print(f"  Moved alias {d.name} -> {dest}")
            moved += 1
        if moved:
            lock.save()
        else:
            print("  No skill aliases found")
        return moved

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

        unified_rules = self.env.rules
        unified_rules.parent.mkdir(parents=True, exist_ok=True)

        raw = self._read_rules_source(legacy_rules)
        # Split on migration markers first so each previously appended chunk
        # dedupes independently against the unified store and other chunks.
        chunks = [
            self._strip_synced_rules(c) for c in re.split(r"<!-- Migrated from [\w.-]+ -->", raw)
        ]
        existing = unified_rules.read_text() if unified_rules.exists() else ""
        existing_norm = self._normalize_rules(existing)
        seen: set = set()
        kept = []
        for chunk in chunks:
            n = self._normalize_rules(chunk)
            # Substring check against the existing file catches chunks already
            # present there; exact match against seen dedupes repeats without
            # dropping a distinct chunk that is a substring of another chunk.
            if not n or n in existing_norm or n in seen:
                continue
            kept.append(chunk)
            seen.add(n)
        additional = "\n\n".join(kept)

        if not unified_rules.exists():
            if additional:
                unified_rules.write_text(additional + "\n")
                print(f"  Migrated rules to: {unified_rules}")
            return

        # Unified already has content: it is the master copy. Appending more
        # provider text here is how the file grew duplicates, so divergence is
        # reported for manual merge instead of written.
        if not additional:
            print(f"  Rules already up to date: {legacy_rules}")
            return
        print(
            f"  Rules differ in {legacy_rules}; unified AGENTS.md is master "
            "(skipped - merge manually if needed)"
        )

    @staticmethod
    def _normalize_rules(text: str) -> str:
        """Whitespace-insensitive form for dedupe comparisons."""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _strip_synced_rules(text: str) -> str:
        """Remove ai-config managed blocks (including nested ones) and
        migration markers so previously exported/migrated content is never
        re-imported into the unified store."""
        text = strip_managed_markers(text)
        text = re.sub(r"<!-- Migrated from [\w.-]+ -->\n?", "", text)
        return text.strip()

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
            project_config = self._find_project_path(provider, "project_config", project_root)
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
            project_mcp = self._find_project_path(provider, "project_mcp", project_root)
            if project_mcp and project_mcp.exists() and project_mcp.is_file():
                try:
                    legacy_config = self._load_json_safe(project_mcp)
                    if legacy_config:
                        spec = PROVIDERS[provider]
                        servers = extract_mcp_servers(spec, legacy_config)
                        if servers:
                            legacy_config = {"context_servers": servers}
                    incoming = None
                    if legacy_config:
                        incoming = legacy_config.get(
                            "context_servers", legacy_config.get("mcpServers")
                        )
                    if incoming:
                        project_mcp_unified = ai_dir / "mcp-config.json"

                        if project_mcp_unified.exists():
                            merged_mcp = load_json(project_mcp_unified)
                            existing_servers = deep_merge(
                                merged_mcp.pop("mcpServers", {}),
                                merged_mcp.get("context_servers", {}),
                            )
                            merged_mcp["context_servers"] = deep_merge(existing_servers, incoming)
                        else:
                            merged_mcp = {"context_servers": incoming}

                        save_json(project_mcp_unified, merged_mcp)
                        print(f"Migrated {provider} project MCP config to {project_mcp_unified}")

                        # Seed project-level mcp scope the same way: the
                        # provider keeps the servers its project file had.
                        proj_conf_path = ai_dir / "config.json"
                        proj_conf = load_json(proj_conf_path) if proj_conf_path.exists() else {}
                        prov_scope = proj_conf.setdefault("providers", {}).setdefault(provider, {})
                        if isinstance(prov_scope, dict) and "mcp" not in prov_scope:
                            prov_scope["mcp"] = {"include": sorted(incoming)}
                            save_json(proj_conf_path, proj_conf)
                except ConfigError:
                    pass

            # Migrate project local config
            project_local = self._find_project_path(provider, "project_local", project_root)
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
            project_skills = self._find_project_path(provider, "project_skills", project_root)
            if project_skills and project_skills.exists():
                self._import_skills_dir(project_skills, ai_dir / "skills", provider)

            # Migrate project rules
            project_rules = self._find_project_path(provider, "project_rules", project_root)
            if project_rules and project_rules.exists():
                unified_rules = ai_dir / "AGENTS.md"
                if not unified_rules.exists():
                    unified_rules.write_text(self._read_rules_source(project_rules))
                    print(f"Migrated {provider} project rules to {unified_rules}")

    def _copy_skills_to_global(self, skills_dir: Path, source_label: str = "") -> int:
        """Copy all skills from a directory to the global ~/.agents/skills location."""
        if not skills_dir or not skills_dir.exists():
            return 0

        return self._import_skills_dir(skills_dir, self.env.skills, "project")

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

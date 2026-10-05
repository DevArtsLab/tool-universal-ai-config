"""
Sync engine: renders the unified ~/.agents configuration back out to each
provider's native locations (MCP files, rules files, skills dirs, config files).

Migration imports provider -> unified. Sync exports unified -> provider.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import UnifiedConfig, deep_merge
from .environment import AgentEnv, find_project_root
from .formats import load_any_safe, save_any, FormatError
from .providers import PROVIDERS, ProviderSpec, SyncTargets, expand, render_mcp_servers

BLOCK_BEGIN = "<!-- BEGIN ai-config managed -->"
BLOCK_END = "<!-- END ai-config managed -->"


@dataclass
class SyncAction:
    provider: str
    kind: str  # config | mcp | rules | skills
    path: Path
    status: str  # planned | written | skipped | error
    detail: str = ""


@dataclass
class SyncResult:
    actions: List[SyncAction] = field(default_factory=list)

    def add(self, provider, kind, path, status, detail=""):
        self.actions.append(SyncAction(provider, kind, Path(path), status, detail))


def _upsert_managed_block(path: Path, content: str) -> None:
    """Insert or replace the ai-config managed block in a text file."""
    block = f"{BLOCK_BEGIN}\n{content.rstrip()}\n{BLOCK_END}\n"
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(block)
        return

    existing = path.read_text()
    if BLOCK_BEGIN in existing and BLOCK_END in existing:
        before = existing.split(BLOCK_BEGIN)[0]
        after = existing.split(BLOCK_END, 1)[1]
        path.write_text(f"{before}{block}{after.lstrip()}")
    else:
        path.write_text(f"{existing.rstrip()}\n\n{block}")


class SyncEngine:
    """Writes unified configuration to provider-native locations."""

    def __init__(self, env: Optional[AgentEnv] = None):
        self.env = env or AgentEnv()
        self.config = UnifiedConfig(self.env)

    def sync(
        self,
        providers: Optional[List[str]] = None,
        project: bool = False,
        all_providers: bool = False,
        dry_run: bool = False,
    ) -> SyncResult:
        from .providers import detect_installed

        result = SyncResult()

        if providers:
            unknown = [p for p in providers if p not in PROVIDERS]
            for name in unknown:
                result.add(name, "-", Path(""), "error", f"unknown provider")
            targets = [p for p in providers if p in PROVIDERS]
        elif all_providers:
            targets = list(PROVIDERS.keys())
        else:
            targets = detect_installed()
            if not targets:
                print(
                    "No providers detected. Use --all to sync to every provider "
                    "or --provider <name> to force one."
                )

        project_root = find_project_root() if project else None
        if project and not project_root:
            print("Error: not in a project directory (no .git or .ai found)")
            return result

        unified = (
            self.config.get_merged_config(cwd=project_root)
            if project_root
            else self.config.load_unified()
        )
        mcp_servers = unified.get("mcpServers", {})
        provider_settings = unified.get("providers", {})
        rules_text = self._read_rules(project_root)
        skills_dir = (project_root / ".ai" / "skills") if project_root else self.env.skills

        for name in targets:
            spec = PROVIDERS[name]
            scope = spec.project if project_root else spec.user
            base = project_root if project_root else None
            settings = provider_settings.get(name, {})
            self._sync_provider(
                spec,
                scope,
                base,
                settings,
                mcp_servers,
                rules_text,
                skills_dir,
                result,
                dry_run,
            )

        return result

    def _sync_provider(
        self,
        spec: ProviderSpec,
        scope: SyncTargets,
        base: Optional[Path],
        settings: Dict[str, Any],
        mcp_servers: Dict[str, Any],
        rules_text: Optional[str],
        skills_dir: Path,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        # Config file: merge provider-specific settings into native config.
        # Unified-namespace keys never belong in a native config file.
        reserved = {"mcpServers", "mcp_servers", "context_servers", "servers", "skills"}
        native_settings = {k: v for k, v in settings.items() if k not in reserved}
        config_path = self._resolve(scope.config_file, base)
        if config_path and native_settings:
            self._write_merged(config_path, native_settings, spec.name, "config", result, dry_run)

        # MCP servers
        mcp_path = self._resolve(scope.mcp_file, base)
        if mcp_path and mcp_servers and scope.mcp_key:
            rendered = render_mcp_servers(scope.mcp_style, mcp_servers)
            self._write_merged(
                mcp_path,
                {scope.mcp_key: rendered},
                spec.name,
                "mcp",
                result,
                dry_run,
            )

        # Rules
        if rules_text and scope.rules_path and scope.rules_mode != "none":
            rules_path = self._resolve(scope.rules_path, base)
            if rules_path:
                self._write_rules(
                    rules_path, rules_text, scope.rules_mode, spec.name, result, dry_run
                )

        # Skills
        if scope.skills_dir and skills_dir and skills_dir.exists():
            target_dir = self._resolve(scope.skills_dir, base)
            if target_dir:
                self._write_skills(skills_dir, target_dir, spec.name, result, dry_run)

    def _resolve(self, path_str: Optional[str], base: Optional[Path]) -> Optional[Path]:
        if not path_str:
            return None
        if base is not None:
            return base / path_str
        return expand(path_str)

    def _write_merged(
        self,
        path: Path,
        fragment: Dict[str, Any],
        provider: str,
        kind: str,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        if dry_run:
            result.add(provider, kind, path, "planned", f"would merge: {list(fragment.keys())}")
            return
        try:
            existing = load_any_safe(path) if path.exists() else {}
            save_any(path, deep_merge(existing, fragment))
            result.add(provider, kind, path, "written")
        except FormatError as e:
            result.add(provider, kind, path, "error", str(e))

    def _write_rules(
        self, path: Path, content: str, mode: str, provider: str, result: SyncResult, dry_run: bool
    ) -> None:
        if mode in ("mdc_dir", "md_dir"):
            path = path / ("ai-config.mdc" if mode == "mdc_dir" else "ai-config.md")
            if mode == "mdc_dir":
                content = (
                    "---\ndescription: Unified AI agent rules "
                    "(managed by ai-config)\nalwaysApply: true\n---\n\n" + content
                )
            if dry_run:
                result.add(provider, "rules", path, "planned", "would write")
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if content.endswith("\n") else content + "\n")
            result.add(provider, "rules", path, "written")
            return

        # file mode: managed block upsert
        if dry_run:
            result.add(provider, "rules", path, "planned", "would upsert managed block")
            return
        _upsert_managed_block(path, content)
        result.add(provider, "rules", path, "written")

    def _write_skills(
        self, src_dir: Path, dst_dir: Path, provider: str, result: SyncResult, dry_run: bool
    ) -> None:
        for skill in sorted(src_dir.iterdir()):
            if not skill.is_dir() or not (skill / "SKILL.md").exists():
                continue
            target = dst_dir / skill.name
            target_skill = target / "SKILL.md"
            if (
                target_skill.exists()
                and target_skill.read_text() == (skill / "SKILL.md").read_text()
            ):
                continue
            if dry_run:
                result.add(provider, "skills", target, "planned", f"would copy {skill.name}")
                continue
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill / "SKILL.md", target / "SKILL.md")
            result.add(provider, "skills", target, "written", skill.name)

    def _read_rules(self, project_root: Optional[Path]) -> Optional[str]:
        """Unified rules: user AGENTS.md, plus project AGENTS.md if syncing a project."""
        parts = []
        user_rules = self.env.config / "AGENTS.md"
        if user_rules.exists():
            parts.append(user_rules.read_text())
        if project_root:
            project_rules = project_root / ".ai" / "AGENTS.md"
            if project_rules.exists():
                parts.append(project_rules.read_text())
        return "\n\n".join(parts) if parts else None

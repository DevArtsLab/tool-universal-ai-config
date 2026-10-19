"""
Sync engine: renders the unified ~/.agents configuration back out to each
provider's native locations (MCP files, rules files, skills dirs, config files).

Migration imports provider -> unified. Sync exports unified -> provider.
"""

import re
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

# Tracks which skill dirs under a provider's skills_dir were written by
# ai-config, so --prune only ever removes managed skills and never deletes
# skills the user placed there themselves.
SKILLS_MANIFEST = ".ai-config-skills"

_BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)
_ORPHAN_MARKER_RE = re.compile(r"<!-- (?:BEGIN|END) ai-config managed -->\n?")


def strip_managed_markers(text: str) -> str:
    """Remove every ai-config managed block from text.

    A non-greedy BEGIN..END match removes the innermost span first, so
    repeating it flattens nested blocks left behind by older exports whose
    content itself contained the markers. A final pass drops orphan markers
    (an END whose BEGIN was consumed by an outer span).
    """
    while True:
        stripped = _BLOCK_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return _ORPHAN_MARKER_RE.sub("", text)


def dirs_equal(a: Path, b: Path) -> bool:
    """True when both directories hold the same files with equal bytes."""
    if not a.is_dir() or not b.is_dir():
        return False
    a_files = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    b_files = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    if a_files != b_files:
        return False
    return all((a / rel).read_bytes() == (b / rel).read_bytes() for rel in a_files)


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

    # Remove every existing managed block, including nested ones: leftover
    # blocks from older runs would otherwise accumulate on each sync.
    existing = strip_managed_markers(path.read_text()).rstrip()
    path.write_text(f"{existing}\n\n{block}" if existing else block)


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
        prune: bool = False,
        dry_run: bool = False,
    ) -> SyncResult:
        result = SyncResult()

        project_root = find_project_root() if project else None
        if project and not project_root:
            print("Error: not in a project directory (no .git or .ai found)")
            return result

        unified = (
            self.config.get_merged_config(cwd=project_root)
            if project_root
            else self.config.load_unified()
        )
        mcp_servers = unified.get("context_servers", {})
        provider_settings = unified.get("providers", {})
        skills_conf = unified.get("skills", {})

        if providers:
            unknown = [p for p in providers if p not in PROVIDERS]
            for name in unknown:
                result.add(name, "-", Path(""), "error", f"unknown provider")
            targets = [p for p in providers if p in PROVIDERS]
        elif all_providers:
            targets = list(PROVIDERS.keys())
        else:
            # Export is opt-in: only providers with providers.<name>.sync: true
            # in the unified config receive writes. Detection alone is never
            # enough to push config (or credentials) into a provider file.
            targets = [
                name
                for name, cfg in provider_settings.items()
                if isinstance(cfg, dict) and cfg.get("sync") is True and name in PROVIDERS
            ]
            if not targets:
                print(
                    "No providers opted in to sync. Set "
                    '"providers.<name>.sync": true in '
                    "~/.agents/config/config.json, or pass --provider <name> / "
                    "--all for an explicit one-off export."
                )
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
                skills_conf,
                rules_text,
                skills_dir,
                result,
                prune,
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
        skills_conf: Dict[str, Any],
        rules_text: Optional[str],
        skills_dir: Path,
        result: SyncResult,
        prune: bool,
        dry_run: bool,
    ) -> None:
        # Config file: merge provider-specific settings into native config.
        # Unified-namespace keys never belong in a native config file.
        reserved = {
            "mcpServers",
            "mcp_servers",
            "context_servers",
            "servers",
            "skills",
            "mcp",
            "sync",
        }
        native_settings = {k: v for k, v in settings.items() if k not in reserved}
        config_path = self._resolve(scope.config_file, base)
        if config_path and native_settings:
            self._write_merged(config_path, native_settings, spec.name, "config", result, dry_run)

        # MCP servers, filtered through per-provider scoping
        scoped = self._filter_mcp(settings.get("mcp"), mcp_servers)
        mcp_path = self._resolve(scope.mcp_file, base)
        if mcp_path and scoped and scope.mcp_key:
            rendered = render_mcp_servers(scope.mcp_style, scoped)
            self._write_merged(
                mcp_path,
                {scope.mcp_key: rendered},
                spec.name,
                "mcp",
                result,
                dry_run,
                replace_key=scope.mcp_key if prune else None,
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
            names = self._scoped_skill_names(settings.get("skills"), skills_conf, skills_dir)
            if target_dir and names is not None:
                self._write_skills(skills_dir, target_dir, spec.name, names, result, prune, dry_run)

    def _resolve(self, path_str: Optional[str], base: Optional[Path]) -> Optional[Path]:
        if not path_str:
            return None
        if base is not None:
            return base / path_str
        return expand(path_str)

    @staticmethod
    def _filter_mcp(mcp_conf: Optional[Dict[str, Any]], servers: Dict[str, Any]) -> Dict[str, Any]:
        """Drop disabled entries, then apply providers.<name>.mcp scoping:
        {"include": [...], "exclude": [...]}.

        include: sync only the named servers. exclude: sync all except the named.
        Neither: sync everything. A server flagged "disabled": true is dormant
        inventory in the unified store and is never exported, even when named
        in include.
        """
        active = {
            k: v
            for k, v in servers.items()
            if not (isinstance(v, dict) and v.get("disabled") is True)
        }
        if not isinstance(mcp_conf, dict):
            return active
        include = mcp_conf.get("include")
        if isinstance(include, list):
            return {k: v for k, v in active.items() if k in include}
        exclude = mcp_conf.get("exclude") or []
        if isinstance(exclude, list) and exclude:
            return {k: v for k, v in active.items() if k not in exclude}
        return active

    @staticmethod
    def _list_skill_names(skills_dir: Path) -> List[str]:
        """Skill names in a directory: subdirs containing a SKILL.md."""
        return sorted(
            d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        )

    def _scoped_skill_names(
        self,
        prov_conf: Optional[Dict[str, Any]],
        global_conf: Optional[Dict[str, Any]],
        skills_dir: Path,
    ) -> Optional[List[str]]:
        """Skill names in scope for one provider, or None when the provider
        opted out of skills entirely (providers.<name>.skills.enabled: false).

        The global skills.enabled list is an allowlist when non-empty.
        providers.<name>.skills then narrows further with include/exclude,
        mirroring the MCP scoping rules.
        """
        if isinstance(prov_conf, dict) and prov_conf.get("enabled") is False:
            return None
        names = self._list_skill_names(skills_dir)
        enabled = (global_conf or {}).get("enabled")
        if isinstance(enabled, list) and enabled:
            names = [n for n in names if n in enabled]
        if not isinstance(prov_conf, dict):
            return names
        include = prov_conf.get("include")
        if isinstance(include, list):
            return [n for n in names if n in include]
        exclude = prov_conf.get("exclude")
        if isinstance(exclude, list) and exclude:
            return [n for n in names if n not in exclude]
        return names

    @staticmethod
    def _server_keys(value: Any) -> set:
        """Server names from a native value: dict keys, or 'name' fields in
        a list-style collection (e.g. Continue's YAML list)."""
        if isinstance(value, dict):
            return set(value.keys())
        if isinstance(value, list):
            return {i["name"] for i in value if isinstance(i, dict) and "name" in i}
        return set()

    def _write_merged(
        self,
        path: Path,
        fragment: Dict[str, Any],
        provider: str,
        kind: str,
        result: SyncResult,
        dry_run: bool,
        replace_key: Optional[str] = None,
    ) -> None:
        """Merge fragment into a config file. When replace_key is set, that
        top-level key is replaced wholesale (prune mode) instead of merged."""
        existing = load_any_safe(path) if path.exists() else {}

        removed: List[str] = []
        if replace_key:
            old_keys = self._server_keys(existing.get(replace_key))
            new_keys = self._server_keys(fragment.get(replace_key))
            removed = sorted(old_keys - new_keys)
            existing[replace_key] = fragment[replace_key]
            merged = existing
        else:
            merged = deep_merge(existing, fragment)

        detail = f"remove: {removed}" if removed else ""
        if dry_run:
            action = "would replace" if replace_key else "would merge"
            result.add(
                provider,
                kind,
                path,
                "planned",
                f"{action}: {list(fragment.keys())}" + (f" | {detail}" if detail else ""),
            )
            return
        try:
            if removed:
                shutil.copy2(path, path.with_name(path.name + ".backup"))
            save_any(path, merged)
            result.add(
                provider,
                kind,
                path,
                "written",
                f"pruned {len(removed)} server(s)" if removed else "",
            )
        except FormatError as e:
            result.add(provider, kind, path, "error", str(e))

    def _write_rules(
        self, path: Path, content: str, mode: str, provider: str, result: SyncResult, dry_run: bool
    ) -> None:
        # The exported text must never carry managed-block markers: a unified
        # rules file that acquired them through a buggy import would otherwise
        # nest blocks inside the block on every sync.
        content = strip_managed_markers(content)
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
        self,
        src_dir: Path,
        dst_dir: Path,
        provider: str,
        names: List[str],
        result: SyncResult,
        prune: bool,
        dry_run: bool,
    ) -> None:
        """Copy whole skill directories (SKILL.md plus companion files) to the
        provider. A manifest file records what ai-config wrote so --prune can
        remove stale managed skills without touching user-managed ones."""
        manifest_path = dst_dir / SKILLS_MANIFEST
        managed = set(manifest_path.read_text().split()) if manifest_path.is_file() else set()
        keep = set(names)

        for name in names:
            src = src_dir / name
            target = dst_dir / name
            if dirs_equal(src, target):
                managed.add(name)
                continue
            if dry_run:
                result.add(provider, "skills", target, "planned", f"would copy {name}")
                managed.add(name)
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            result.add(provider, "skills", target, "written", name)
            managed.add(name)

        stale = sorted(managed - keep)
        if prune:
            for name in stale:
                target = dst_dir / name
                if dry_run:
                    result.add(provider, "skills", target, "planned", f"would remove {name}")
                    continue
                if target.is_dir():
                    shutil.rmtree(target)
                result.add(provider, "skills", target, "written", f"removed {name}")
            managed -= set(stale)

        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text("\n".join(sorted(managed)) + ("\n" if managed else ""))

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

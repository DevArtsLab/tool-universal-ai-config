"""
CLI interface for universal AI configuration management.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional
from . import __version__
from .environment import AgentEnv, find_project_root, project_dir_name, project_dir_names
from .config import UnifiedConfig, ConfigError
from .lockfile import LOCK_NAME, SkillsLock, dir_hash
from .migration import ProviderMigrator, MigrationError, SKILL_CONFLICTS_DIR
from .providers import PROVIDERS, expand
from .sync import SyncEngine


def _pick_destination(default: Path) -> Path:
    """Interactive destination pick for migrate. Enter or "1" keeps the
    default user store; "2" accepts a custom path. Non-answers (EOF,
    Ctrl-C, empty path) also keep the default."""
    print("\nDestination for migrated config:")
    print(f"  1) {default}  (default user store)")
    print("  2) Enter a path")
    try:
        choice = input("Choice [1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    if choice == "2":
        try:
            raw = input("Path: ").strip()
        except (EOFError, KeyboardInterrupt):
            return default
        if raw:
            return Path(raw).expanduser()
    return default


class CLI:
    """Command-line interface for AI configuration management."""

    def __init__(self):
        self.env = AgentEnv()
        self.config = UnifiedConfig(self.env)
        self.migrator = ProviderMigrator(self.env)

    def init(self, fresh: bool = False) -> None:
        """Initialize new unified configuration structure."""
        print("Initializing universal AI configuration...")

        if fresh:
            if self.env.config.exists():
                print(f"Removing existing config at: {self.env.config}")
                shutil.rmtree(self.env.config)
            master_rules = self.env.base / "AGENTS.md"
            if master_rules.exists():
                master_rules.unlink()

        # Create directory structure
        created = self.env.initialize_dirs()
        for dir_path in created:
            print(f"  Created: {dir_path}")

        # Create default unified config
        if not self.config.unified_config_path.exists():
            default_config = self.config._get_default_config()
            self.config.save_unified(default_config)
            print(f"  Created: {self.config.unified_config_path}")

        # One-time relocation: rules belong at the base, not under config/
        legacy_rules = self.env.config / "AGENTS.md"
        master_rules = self.env.base / "AGENTS.md"
        if legacy_rules.exists() and not master_rules.exists():
            legacy_rules.rename(master_rules)
            print(f"  Moved rules to: {master_rules}")

        # Create default AGENTS.md
        agents_md = self.env.rules
        if not agents_md.exists():
            agents_md.write_text(
                "# Universal AI Configuration\n\n## Global Rules\n\nAdd your global AI agent rules here.\n"
            )
            print(f"  Created: {agents_md}")

        # Create default mcp-config.json
        if not self.config.mcp_config_path.exists():
            self.config.save_mcp_servers({})
            print(f"  Created: {self.config.mcp_config_path}")

        print("\n✓ Initialization complete")
        print(f"Config directory: {self.env.config}")

    def migrate(
        self,
        provider: Optional[str] = None,
        project: bool = False,
        all_projects: bool = False,
        interactive: Optional[bool] = None,
        reconcile_aliases: bool = False,
        dest: Optional[str] = None,
    ) -> None:
        """Migrate existing provider configurations."""
        print("Starting migration...")

        if interactive is not None:
            self.migrator.interactive = interactive

        if dest and project:
            print(
                "Error: --dest does not apply to --project; "
                "the project .agents/ dir is the destination"
            )
            sys.exit(1)

        # Destination: explicit --dest wins; an interactive pick runs when
        # stdin is a TTY (the migrate default); --no-interactive silently
        # keeps the default user store so scripts never block.
        env = self.env
        migrator = self.migrator
        target = Path(dest).expanduser() if dest else None
        if target is None and not project and migrator.interactive:
            target = _pick_destination(env.base)
        if target is not None and target.resolve() != env.base.resolve():
            env = AgentEnv(base=target)
            env.initialize_dirs()
            migrator = ProviderMigrator(env, interactive=migrator.interactive)
            print(f"Destination: {env.base}")

        if reconcile_aliases:
            if provider or project or all_projects:
                print(
                    "Error: --reconcile-aliases cannot combine with a provider "
                    "argument, --project, or --all-projects"
                )
                sys.exit(1)
            moved = migrator.reconcile_skill_aliases(env.skills)
            print(f"\n✓ Reconciled {moved} skill alias(es) into {env.base}/skill-conflicts/")
            return

        if all_projects:
            # Scan all projects and migrate their skills to global
            migrator.migrate_all_project_skills()
        elif project:
            # Migrate project configs
            project_root = find_project_root()
            if not project_root:
                print("Error: Not in a project directory (no .git, .jj, or .agents/.ai found)")
                return

            print(f"Migrating project at: {project_root}")
            migrator.migrate_project(project_root)
        else:
            # Migrate user configs
            if provider:
                # Migrate specific provider
                try:
                    migrator.migrate_provider(provider)
                except MigrationError as e:
                    print(f"Error: {e}")
                    sys.exit(1)
            else:
                # Migrate all detected providers
                results = migrator.migrate_all()
                if not results:
                    print("No legacy configurations found to migrate")
                    return

        print("\n✓ Migration complete")
        print("Run 'ai-config validate' to verify the setup")

    def validate(self) -> None:
        """Validate the unified configuration setup."""
        print("Validating configuration...")

        issues = []

        # Check directories exist
        required_dirs = [self.env.config, self.env.data, self.env.state, self.env.cache]

        for dir_path in required_dirs:
            if not dir_path.exists():
                issues.append(f"Missing directory: {dir_path}")
            else:
                print(f"  ✓ Directory exists: {dir_path}")

        # Check unified config
        if not self.config.unified_config_path.exists():
            issues.append(f"Missing unified config: {self.config.unified_config_path}")
        else:
            try:
                config = self.config.load_unified()
                print(f"  ✓ Unified config valid: {self.config.unified_config_path}")

                # Validate structure
                required_keys = ["shared", "providers", "context_servers", "skills"]
                for key in required_keys:
                    if key not in config:
                        issues.append(f"Missing key in config: {key}")
                    else:
                        print(f"    ✓ Contains: {key}")

                # Validate provider configs
                for provider, settings in config.get("providers", {}).items():
                    print(f"  ✓ Provider config: {provider}")

                # Validate MCP servers
                for server in config.get("context_servers", {}).keys():
                    print(f"  ✓ MCP server: {server}")

            except ConfigError as e:
                issues.append(f"Invalid unified config: {e}")

        # Check skills directory
        skills_dir = self.env.skills
        if skills_dir.exists():
            skill_count = len(list(skills_dir.glob("*/SKILL.md")))
            print(f"  ✓ Skills directory: {skill_count} skills found")

        # Check project config if in project
        project_root = find_project_root()
        if project_root:
            ai_dir = project_root / project_dir_name(project_root)
            if ai_dir.exists():
                print(f"  ✓ Project config: {ai_dir}")

                if (ai_dir / "config.json").exists():
                    print(f"    ✓ Project config.json exists")
                if (ai_dir / "config.local.json").exists():
                    print(f"    ✓ Project config.local.json exists")

        # Report results
        if issues:
            print("\n❌ Validation failed:")
            for issue in issues:
                print(f"  - {issue}")
            sys.exit(1)
        else:
            print("\n✓ All validations passed")

    def status(self) -> None:
        """Show current configuration status."""
        print("Universal AI Configuration Status")
        print("=" * 40)

        # Config locations
        print(f"\nConfig directory: {self.env.config}")
        print(f"Data directory: {self.env.data}")
        print(f"State directory: {self.env.state}")
        print(f"Cache directory: {self.env.cache}")

        # Unified config status
        if self.config.unified_config_path.exists():
            print(f"\n✓ Unified config exists")
            config = self.config.load_unified()

            # Providers
            providers = config.get("providers", {})
            if providers:
                print(f"\nConfigured providers: {', '.join(providers.keys())}")
                sync_enabled = [
                    n for n, c in providers.items() if isinstance(c, dict) and c.get("sync") is True
                ]
                print(
                    f"Sync-enabled (export): "
                    f"{', '.join(sync_enabled) if sync_enabled else 'none'}"
                )
            else:
                print(f"\nNo providers configured yet")

            # MCP servers
            mcp_servers = config.get("context_servers", {})
            if mcp_servers:
                print(f"MCP servers: {', '.join(mcp_servers.keys())}")
            else:
                print(f"MCP servers: None")

            # Skills
            skills = config.get("skills", {})
            enabled = skills.get("enabled", [])
            if enabled:
                print(f"Enabled skills: {', '.join(enabled)}")
            else:
                print(f"Enabled skills: None")
        else:
            print(f"\n✗ Unified config not found")
            print(f"Run 'ai-config init' to create it")

        self._print_skills_lock()

        # Project status
        project_root = find_project_root()
        if project_root:
            ai_dir = project_root / project_dir_name(project_root)
            print(f"\n✓ Project detected: {project_root}")
            if ai_dir.exists():
                print(f"  Project config: {ai_dir}")
            else:
                print(f"  No .agents/ directory in project")
                print(f"  Run 'ai-config init-project' to create it")
        else:
            print(f"\nNot in a project directory")

    def _print_skills_lock(self) -> None:
        """Summarize skills lockfiles (global and project): source freshness
        plus per-provider sync state (in sync / stale / drifted / missing)
        for recorded pushes."""
        self._print_lock_section(self.env.base, self.env.skills, project_root=None)
        project_root = find_project_root()
        if project_root:
            self._print_lock_section(
                project_root / project_dir_name(project_root),
                project_root / project_dir_name(project_root) / "skills",
                project_root,
            )

    def _print_lock_section(
        self, base: Path, unified_skills: Path, project_root: Optional[Path]
    ) -> None:
        lock_path = base / LOCK_NAME
        if not lock_path.is_file():
            return
        lock = SkillsLock(base)
        pruned = lock.prune_conflicts()
        sources_changed = False
        if unified_skills.is_dir():
            sources_changed = lock.reconcile_sources(unified_skills)
        if pruned or sources_changed:
            lock.save()
        skills = lock.data.get("skills", {})
        providers = lock.data.get("providers", {})
        label = "Project skills lock" if project_root else "Skills lock"
        tracked = len(skills) if isinstance(skills, dict) else 0
        print(f"\n{label}: {tracked} tracked ({lock_path})")

        # Per-provider state for each recorded push. Live-hashes the provider
        # copy so locally edited skills surface as drifted.
        if isinstance(providers, dict):
            for prov_name, prov_data in sorted(providers.items()):
                if not isinstance(prov_data, dict):
                    continue
                receipts = prov_data.get("skills", {})
                if not isinstance(receipts, dict) or not receipts:
                    continue
                spec = PROVIDERS.get(prov_name)
                if project_root:
                    target_dir = (
                        project_root / spec.project.skills_dir
                        if spec and spec.project.skills_dir
                        else None
                    )
                else:
                    target_dir = (
                        expand(spec.user.skills_dir) if spec and spec.user.skills_dir else None
                    )
                counts = {"in sync": 0, "stale": 0, "drifted": 0, "missing": 0}
                flagged = []
                for name, receipt in sorted(receipts.items()):
                    if not isinstance(receipt, dict):
                        continue
                    pushed = receipt.get("hash")
                    # Live-hash the unified copy: the recorded source hash only
                    # refreshes on sync, so it cannot flag "stale" on its own.
                    unified_dir = unified_skills / name
                    source = dir_hash(unified_dir) if unified_dir.is_dir() else None
                    target = (target_dir / name) if target_dir else None
                    if target is None or not target.is_dir():
                        state = "missing"
                    else:
                        live = dir_hash(target)
                        if live != pushed:
                            state = "drifted"
                        elif source is not None and pushed != source:
                            state = "stale"
                        else:
                            state = "in sync"
                    counts[state] += 1
                    if state != "in sync":
                        flagged.append(f"{name} ({state})")
                summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
                print(f"  {prov_name}: {summary}")
                for item in flagged:
                    print(f"    - {item}")

        conflicts = lock.data.get("conflicts", {})
        if isinstance(conflicts, dict) and conflicts:
            total = sum(len(v) for v in conflicts.values() if isinstance(v, list))
            print(f"\nSkill conflicts: {total} recorded ({base / SKILL_CONFLICTS_DIR}/)")
            for name, entries in sorted(conflicts.items()):
                if not isinstance(entries, list) or not entries:
                    continue
                latest = entries[-1]
                if not isinstance(latest, dict):
                    continue
                where = latest.get("quarantinedTo") or "unresolved"
                print(f"  {name}: {latest['resolution']} from {latest['provider']} -> {where}")

    def init_project(self, template: Optional[str] = None) -> None:
        """Initialize .agents/ directory in current project (legacy .ai/ kept working)."""
        project_root = find_project_root()
        if not project_root:
            print("Error: Not in a git repository")
            print("Initialize a git repository first, or run in an existing project")
            sys.exit(1)

        if template:
            self._init_project_from_template(project_root, Path(template).expanduser())
            return

        names = project_dir_names()
        for name in names:
            existing = project_root / name
            if existing.exists():
                print(f"Project already initialized: {existing}")
                return

        ai_dir = project_root / names[0]
        print(f"Initializing {ai_dir.name}/ in {project_root}")
        ai_dir.mkdir()

        # Create project config
        project_config = ai_dir / "config.json"
        project_config.write_text(
            json.dumps(
                {
                    "permissions": {"allow": [], "deny": [], "ask": []},
                    "read_config_from": {"windsurf": False, "claude": False},
                },
                indent=2,
            )
        )
        print(f"  Created: {project_config}")

        # Create project AGENTS.md
        agents_md = ai_dir / "AGENTS.md"
        agents_md.write_text("# Project Rules\n\nAdd project-specific AI agent rules here.\n")
        print(f"  Created: {agents_md}")

        # Create skills directory
        skills_dir = ai_dir / "skills"
        skills_dir.mkdir()
        print(f"  Created: {skills_dir}")

        # Update .gitignore
        gitignore = project_root / ".gitignore"
        gitignore_content = ""
        if gitignore.exists():
            gitignore_content = gitignore.read_text()

        dir_name = ai_dir.name
        local_configs = [
            f"{dir_name}/config.local.json",
            f"{dir_name}/mcp-config.local.json",
            f"{dir_name}/.ai-config-lock.json",
            f"{dir_name}/skill-conflicts/",
        ]

        additions = []
        for local_config in local_configs:
            if local_config not in gitignore_content:
                additions.append(local_config)

        if additions:
            with open(gitignore, "a") as f:
                f.write("\n# AI local configs\n")
                for addition in additions:
                    f.write(f"{addition}\n")
            print(f"  Updated .gitignore")

        print("\n✓ Project initialization complete")

    def _init_project_from_template(self, project_root: Path, template_dir: Path) -> None:
        """Copy a template directory into the project root.

        {{PROJECT_NAME}} is substituted in text files. Existing files are
        never overwritten. The project config dir (.agents/ or .ai/) and
        gitignore entries are still ensured afterwards.
        """
        template_dir = template_dir.resolve()
        if not template_dir.is_dir():
            print(f"Error: template directory not found: {template_dir}")
            sys.exit(1)

        created: List[str] = []
        skipped: List[str] = []
        skip_parts = {".git", ".jj", ".svn", ".hg"}
        for src in sorted(template_dir.rglob("*")):
            rel = src.relative_to(template_dir)
            if any(p in skip_parts for p in rel.parts) or src.name == ".DS_Store":
                continue
            dst = project_root / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            if dst.exists():
                skipped.append(str(rel))
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                text = src.read_text()
            except UnicodeDecodeError:
                shutil.copy2(src, dst)
            else:
                dst.write_text(text.replace("{{PROJECT_NAME}}", project_root.name))
            created.append(str(rel))

        for name in created:
            print(f"  Created: {name}")
        for name in skipped:
            print(f"  Skipped (exists): {name}")

        names = project_dir_names()
        ai_dir = project_root / names[0]
        if not ai_dir.exists():
            ai_dir.mkdir()
            print(f"  Created: {ai_dir.name}/")

        gitignore = project_root / ".gitignore"
        gitignore_content = gitignore.read_text() if gitignore.exists() else ""
        dir_name = ai_dir.name
        local_configs = [
            f"{dir_name}/config.local.json",
            f"{dir_name}/mcp-config.local.json",
            f"{dir_name}/.ai-config-lock.json",
            f"{dir_name}/skill-conflicts/",
        ]
        additions = [c for c in local_configs if c not in gitignore_content]
        if additions:
            with open(gitignore, "a") as f:
                f.write("\n# AI local configs\n")
                for addition in additions:
                    f.write(f"{addition}\n")
            print(f"  Updated .gitignore")

        print("\n✓ Project initialization complete")

    def get_config(self, provider: str) -> None:
        """Get and display configuration for a specific provider."""
        try:
            config = self.config.get_provider_config(provider)
            print(f"Configuration for {provider}:")
            print(json.dumps(config, indent=2))
        except ConfigError as e:
            print(f"Error: {e}")
            sys.exit(1)

    def set_config(self, provider: str, key: str, value: str) -> None:
        """Set a configuration value for a provider."""
        try:
            # Parse value (handle JSON, numbers, booleans)
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                parsed_value = value

            settings = {key: parsed_value}
            self.config.update_provider(provider, settings)
            print(f"✓ Set {key} for {provider}")
        except ConfigError as e:
            print(f"Error: {e}")
            sys.exit(1)

    def sync(
        self,
        providers=None,
        project=False,
        all_providers=False,
        prune=False,
        dry_run=False,
    ) -> None:
        """Write unified config back to provider-native locations."""
        engine = SyncEngine(self.env)

        if dry_run:
            print("Dry run: showing what would be written\n")

        result = engine.sync(
            providers=providers,
            project=project,
            all_providers=all_providers,
            prune=prune,
            dry_run=dry_run,
        )

        if not result.actions:
            print("Nothing to sync")
            return

        by_provider: Dict[str, list] = {}
        for action in result.actions:
            by_provider.setdefault(action.provider, []).append(action)

        for provider, actions in by_provider.items():
            print(f"{provider}:")
            for action in actions:
                if action.status == "error":
                    marker = "!"
                elif action.status in ("written", "planned"):
                    marker = "+"
                else:
                    marker = "-"
                detail = f" ({action.detail})" if action.detail else ""
                print(f"  {marker} {action.kind}: {action.path}{detail}")

        written = sum(1 for a in result.actions if a.status == "written")
        planned = sum(1 for a in result.actions if a.status == "planned")
        errors = sum(1 for a in result.actions if a.status == "error")

        if dry_run:
            print(f"\n{planned} change(s) planned. Run without --dry-run to apply.")
        else:
            print(f"\n✓ Synced {written} file(s)" + (f", {errors} error(s)" if errors else ""))
        if errors:
            sys.exit(1)


def main():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Universal AI Configuration Manager", prog="ai-config"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize new configuration")
    init_parser.add_argument(
        "--fresh", action="store_true", help="Remove existing config and start fresh"
    )

    # migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Migrate existing configurations")
    migrate_parser.add_argument("provider", nargs="?", help="Specific provider to migrate")
    migrate_parser.add_argument("--project", action="store_true", help="Migrate project configs")
    migrate_parser.add_argument(
        "--all-projects",
        action="store_true",
        help="Scan all projects and migrate their skills to global ~/.agents/skills",
    )
    migrate_parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Never prompt on skill conflicts; quarantine the incoming copy",
    )
    migrate_parser.add_argument(
        "--reconcile-aliases",
        action="store_true",
        help="Move legacy '<name>.<provider>' skill dirs to skill-conflicts/",
    )
    migrate_parser.add_argument(
        "--dest",
        metavar="PATH",
        help="Alternate unified destination root for migrated config "
        "(skips the destination prompt)",
    )

    # validate command
    subparsers.add_parser("validate", help="Validate configuration setup")

    # status command
    subparsers.add_parser("status", help="Show configuration status")

    # init-project command
    init_project_parser = subparsers.add_parser(
        "init-project",
        help="Initialize .agents/ in current project (legacy .ai/ still supported)",
    )
    init_project_parser.add_argument(
        "--template",
        metavar="DIR",
        help="Copy a template directory into the project; {{PROJECT_NAME}} "
        "is substituted and existing files are never overwritten",
    )

    # get-config command
    get_config_parser = subparsers.add_parser("get-config", help="Get provider configuration")
    get_config_parser.add_argument("provider", help="Provider name")

    # set-config command
    set_config_parser = subparsers.add_parser("set-config", help="Set provider configuration")
    set_config_parser.add_argument("provider", help="Provider name")
    set_config_parser.add_argument("key", help="Configuration key")
    set_config_parser.add_argument("value", help="Configuration value")

    # sync command
    sync_parser = subparsers.add_parser(
        "sync",
        help="Export unified config to providers opted in via providers.<name>.sync (or use --provider/--all)",
    )
    sync_parser.add_argument(
        "--provider", action="append", help="Sync only this provider (repeatable)"
    )
    sync_parser.add_argument(
        "--project",
        action="store_true",
        help="Sync project-level targets (.cursor/, .vscode/, etc.)",
    )
    sync_parser.add_argument(
        "--all",
        dest="all_providers",
        action="store_true",
        help="Sync to all known providers, even if not detected",
    )
    sync_parser.add_argument(
        "--prune",
        action="store_true",
        help="Make provider MCP lists an exact mirror of unified config and "
        "remove synced skills that left scope (backs up files first; "
        "never deletes skills it did not write)",
    )
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be written without writing"
    )
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cli = CLI()

    if args.command == "init":
        cli.init(fresh=args.fresh)
    elif args.command == "migrate":
        cli.migrate(
            provider=args.provider,
            project=args.project,
            all_projects=args.all_projects,
            interactive=False if args.no_interactive else None,
            reconcile_aliases=args.reconcile_aliases,
            dest=args.dest,
        )
    elif args.command == "validate":
        cli.validate()
    elif args.command == "status":
        cli.status()
    elif args.command == "init-project":
        cli.init_project(args.template)
    elif args.command == "get-config":
        cli.get_config(args.provider)
    elif args.command == "set-config":
        cli.set_config(args.provider, args.key, args.value)
    elif args.command == "sync":
        cli.sync(
            providers=args.provider,
            project=args.project,
            all_providers=args.all_providers,
            prune=args.prune,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()

"""
CLI interface for universal AI configuration management.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional
from .environment import AgentEnv, find_project_root
from .config import UnifiedConfig, ConfigError
from .migration import ProviderMigrator, MigrationError
from .sync import SyncEngine


class CLI:
    """Command-line interface for AI configuration management."""

    def __init__(self):
        self.env = AgentEnv()
        self.config = UnifiedConfig(self.env)
        self.migrator = ProviderMigrator(self.env)

    def init(self, fresh: bool = False) -> None:
        """Initialize new unified configuration structure."""
        print("Initializing universal AI configuration...")

        if fresh and self.env.config.exists():
            print(f"Removing existing config at: {self.env.config}")
            shutil.rmtree(self.env.config)

        # Create directory structure
        created = self.env.initialize_dirs()
        for dir_path in created:
            print(f"  Created: {dir_path}")

        # Create default unified config
        if not self.config.unified_config_path.exists():
            default_config = self.config._get_default_config()
            self.config.save_unified(default_config)
            print(f"  Created: {self.config.unified_config_path}")

        # Create default AGENTS.md
        agents_md = self.env.config / "AGENTS.md"
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
        self, provider: Optional[str] = None, project: bool = False, all_projects: bool = False
    ) -> None:
        """Migrate existing provider configurations."""
        print("Starting migration...")

        if all_projects:
            # Scan all projects and migrate their skills to global
            self.migrator.migrate_all_project_skills()
        elif project:
            # Migrate project configs
            project_root = find_project_root()
            if not project_root:
                print("Error: Not in a project directory (no .git or .ai found)")
                return

            print(f"Migrating project at: {project_root}")
            self.migrator.migrate_project(project_root)
        else:
            # Migrate user configs
            if provider:
                # Migrate specific provider
                try:
                    self.migrator.migrate_provider(provider)
                except MigrationError as e:
                    print(f"Error: {e}")
                    sys.exit(1)
            else:
                # Migrate all detected providers
                results = self.migrator.migrate_all()
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
        skills_dir = self.env.config / "skills"
        if skills_dir.exists():
            skill_count = len(list(skills_dir.glob("*/SKILL.md")))
            print(f"  ✓ Skills directory: {skill_count} skills found")

        # Check project config if in project
        project_root = find_project_root()
        if project_root:
            ai_dir = project_root / ".ai"
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

        # Project status
        project_root = find_project_root()
        if project_root:
            ai_dir = project_root / ".ai"
            print(f"\n✓ Project detected: {project_root}")
            if ai_dir.exists():
                print(f"  Project config: {ai_dir}")
            else:
                print(f"  No .ai/ directory in project")
                print(f"  Run 'ai-config init-project' to create it")
        else:
            print(f"\nNot in a project directory")

    def init_project(self) -> None:
        """Initialize .ai/ directory in current project."""
        project_root = find_project_root()
        if not project_root:
            print("Error: Not in a git repository")
            print("Initialize a git repository first, or run in an existing project")
            sys.exit(1)

        ai_dir = project_root / ".ai"
        if ai_dir.exists():
            print(f"Project already initialized: {ai_dir}")
            return

        print(f"Initializing .ai/ in {project_root}")
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

        local_configs = [".ai/config.local.json", ".ai/mcp_config.local.json"]

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
        self, providers=None, project=False, all_providers=False, prune=False, dry_run=False
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

    # validate command
    subparsers.add_parser("validate", help="Validate configuration setup")

    # status command
    subparsers.add_parser("status", help="Show configuration status")

    # init-project command
    subparsers.add_parser("init-project", help="Initialize .ai/ in current project")

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
        help="Make provider MCP lists an exact mirror of unified config "
        "(removes extras, backs up files first)",
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
        cli.migrate(provider=args.provider, project=args.project, all_projects=args.all_projects)
    elif args.command == "validate":
        cli.validate()
    elif args.command == "status":
        cli.status()
    elif args.command == "init-project":
        cli.init_project()
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

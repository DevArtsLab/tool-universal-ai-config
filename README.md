# Universal AI Configuration

A unified configuration system for AI agents across multiple providers (Devin, Windsurf, Claude, etc.). This tool provides a single source of truth for AI agent settings, skills, MCP servers, and rules.

## Features

- **Unified Configuration**: Single config file for all AI providers
- **XDG-Compliant**: Follows Linux/macOS/Windows directory standards
- **Migration Support**: Automatically migrates existing provider configs
- **Sync**: Writes unified config back to each provider's native files (`ai-config sync`)
- **Project-Local**: Per-project configuration with `.ai/` directory
- **Shared Resources**: MCP servers and skills shared across providers
- **Drift Detection**: Skills lockfile tracks pushed content hashes, so
  locally edited or stale provider copies surface in `status` and are
  backed up rather than overwritten
- **Provider Overrides**: Provider-specific settings when needed

## Supported Providers

| Provider          | Config                        | MCP servers                | Rules                             | Skills |
| ----------------- | ----------------------------- | -------------------------- | --------------------------------- | ------ |
| Devin             | `~/.config/devin/config.json` | `mcp_config.json`          | `AGENTS.md`                       | yes    |
| Windsurf          | `~/.windsurf/config.json`     | `mcp_config.json`          | global rules / `.windsurf/rules/` | yes    |
| Claude            | `~/.claude/settings.json`     | `.mcp.json`                | `CLAUDE.md`                       | yes    |
| Cursor            | `~/.cursor/settings.json`     | `~/.cursor/mcp.json`       | `.cursor/rules/*.mdc`             | yes    |
| Codex CLI         | `~/.codex/config.toml`        | same file (TOML)           | `AGENTS.md`                       | -      |
| Gemini CLI        | `~/.gemini/settings.json`     | `mcpServers` key           | `GEMINI.md`                       | -      |
| VS Code / Copilot | `settings.json`               | `mcp.json` (`servers` key) | `.github/copilot-instructions.md` | -      |
| Zed               | `~/.config/zed/settings.json` | `context_servers` key      | `.rules`                          | -      |
| Continue          | `~/.continue/config.yaml`     | `mcpServers` list          | `.continue/rules/`                | -      |

Sync is **opt-in**: detection alone never pushes anything into a provider.
A provider only receives writes when you set `"providers.<name>.sync": true`
in `~/.agents/config/config.json`, or when you pass `--provider <name>` /
`--all` for an explicit one-off export.

Legacy paths are covered too: the Windsurf line spans Codeium-era
(`~/.codeium/`) through current `~/.windsurf/` locations, and Devin detection
covers both `~/.config/devin/` (active config) and `~/.devin/` (application
data). Migration reads every known path; sync writes to the provider's
current master location (Windsurf skills: `~/.codeium/windsurf/skills/`).

## Installation

### Package Manager (Recommended)

```bash
# uv (or run without installing: uvx ai-config --help)
uv tool install universal-ai-config

# pipx
pipx install universal-ai-config

# pip
pip install universal-ai-config
```

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash
```

The installer prefers uv or pipx when available, and falls back to a managed
virtual environment. It will:

- Install the package and set up the `ai-config` command
- Detect and migrate existing configurations
- Initialize the unified config structure

### Standalone Binaries

Prebuilt binaries for Linux, macOS (Intel and Apple Silicon), and Windows are
attached to each [GitHub release](https://github.com/DevArtsLab/tool-universal-ai-config/releases)

- no Python required.

### Manual Install

```bash
# Clone the repository
git clone https://github.com/DevArtsLab/tool-universal-ai-config.git
cd tool-universal-ai-config

# Install via pip
pip install -e .
```

## Quick Start

### New Users

Initialize a fresh configuration:

```bash
ai-config init
```

Initialize for a project:

```bash
cd your-project
ai-config init-project
```

### Existing Users

Migrate from existing provider configurations:

```bash
ai-config migrate
```

Migrate project-specific configs:

```bash
cd your-project
ai-config migrate --project
```

## Directory Structure

### User-Global Configuration

```
~/.agents/                  # All agent data in one place
  ├── AGENTS.md           # Shared rules (global)
  ├── .ai-config-lock.json # Skills lockfile: hashes, origins, sync receipts
  ├── skill-conflicts/    # Quarantined same-name skills pending resolution
  ├── config/
  │   ├── config.json     # Unified config (all providers read this)
  │   └── mcp-config.json # MCP servers
  ├── skills/             # Shared skills
  │   └── example-skill/
  ├── data/               # Long-term memory, datasets, plugins
  │   ├── memory/
  │   └── plugins/
  ├── state/              # Logs, history, active sessions
  │   ├── logs/
  │   └── history/
  └── cache/              # Model caches, isolated environments
      ├── models/
      └── venv/
```

### Project-Local Configuration

```
.ai/                      # In repository root
  ├── config.json         # Shared team settings
  ├── config.local.json   # Personal overrides (gitignored)
  ├── skills/             # Project-specific skills
  ├── mcp-config.json     # Project MCP servers
  ├── mcp-config.local.json # Project MCP overrides (gitignored)
  └── AGENTS.md           # Project rules
```

## Configuration Format

### Unified Config (`~/.agents/config/config.json`)

```json
{
  "shared": {
    "permissions": {
      "allow": ["Read(**)", "Exec(git)"],
      "deny": ["Exec(sudo)"],
      "ask": ["Write(**/.env*)"]
    }
  },
  "providers": {
    "devin": {
      "permissions": {
        "allow": ["Read(**)", "Exec(git)", "Exec(npm)"]
      }
    }
  },
  "skills": {
    "enabled": [],
    "paths": ["~/.agents/skills/", ".ai/skills/"]
  }
}
```

### MCP Config (`~/.agents/config/mcp-config.json`)

MCP servers are kept in a separate file under the `context_servers` key:

```json
{
  "context_servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

The legacy `mcpServers` key is still accepted on read. Set `"disabled": true`
on a server entry to keep it in the unified store without exporting it - sync
skips disabled servers even when they are named in an `include` list.

## Commands

### `ai-config init [--fresh]`

Initialize new configuration structure.

```bash
ai-config init           # Initialize new config
ai-config init --fresh   # Remove existing and start fresh
```

### `ai-config migrate [provider] [--project]`

Migrate existing provider configurations.

```bash
ai-config migrate              # Migrate all detected providers
ai-config migrate devin        # Migrate specific provider
ai-config migrate --project    # Migrate project configs
ai-config migrate --no-interactive     # Quarantine skill conflicts without prompting
ai-config migrate --reconcile-aliases  # Move legacy <name>.<provider> dirs to skill-conflicts/
```

On a TTY, `migrate` asks how to resolve each same-name skill conflict
(keep / replace / skip); otherwise the incoming copy is quarantined under
`skill-conflicts/<name>/<provider>/` next to the skills dir.

### `ai-config validate`

Validate configuration setup.

```bash
ai-config validate
```

### `ai-config status`

Show current configuration status. When a skills lockfile exists, also
reports per-provider skill state (in sync, stale, drifted, missing) and
any recorded conflicts. Reading live hashes refreshes the lockfile in
place: source entries are reconciled with the skills dir and conflict
records whose parked copies were removed are pruned.

```bash
ai-config status
```

### `ai-config init-project`

Initialize `.ai/` directory in current project.

```bash
ai-config init-project
```

### `ai-config get-config <provider>`

Get configuration for a specific provider.

```bash
ai-config get-config devin
```

### `ai-config sync [--provider NAME] [--project] [--all] [--prune] [--copy] [--dry-run]`

Write the unified config back to each provider's native files: MCP servers
(translated to each provider's format: `mcpServers`, `servers`,
`context_servers`, TOML `mcp_servers`, or YAML lists), rules (as a managed
block in `CLAUDE.md`/`AGENTS.md`/etc., or dedicated rule files), provider
settings, and skills.

```bash
ai-config sync --dry-run      # preview all writes
ai-config sync                # sync providers opted in via config
ai-config sync --provider cursor   # one provider, explicit
ai-config sync --all          # every known provider, explicit
ai-config sync --project      # project-level targets (.cursor/, .vscode/, ...)
ai-config sync --prune        # also remove MCP servers no longer in scope
ai-config sync --copy         # copy skills/rules instead of symlinking
```

Skills sync defaults to **symlinks**: each provider's skills dir links to
the unified copy, so a skill edited in any provider edits the single
source. A provider rules file that holds only the unified `AGENTS.md`
content is linked the same way. Pass `--copy` for plain copies, or when a
provider cannot follow symlinks.

Bare `ai-config sync` only writes to providers that opted in via
`"providers.<name>.sync": true`. Providers can also read the unified config
directly (see Provider Integration) without any file export.

Sync merges by default: existing keys in provider files are preserved, so
servers added outside the unified config survive. Pass `--prune` to make a
provider's MCP list an exact mirror of its scoped unified set and to remove
synced skills that left scope; pruned MCP files are backed up with a
`.backup` suffix first, and skills outside the `.ai-config-skills` manifest
are left untouched. A skill name already claimed by a user-managed dir or
file is preserved under `.ai-config-backups/` in that skills dir - and so
is a managed copy whose contents were edited locally since the recorded
push (drift protection, via the skills lockfile).

#### Per-provider MCP scoping

By default every provider receives the full unified MCP server set. Scope it
in `~/.agents/config/config.json`:

```json
{
  "providers": {
    "cursor": { "mcp": { "include": ["github", "filesystem"] } },
    "claude": { "mcp": { "exclude": ["internal-tools"] } }
  }
}
```

`include` is an allowlist (only those servers sync); `exclude` removes
servers from the full set. Use this to keep credential-bearing MCP configs
out of providers that don't need them. Servers marked `"disabled": true` in
`mcp-config.json` are never exported, even when named in `include`.

#### Per-provider skills scoping

Skills follow the same scoping rules. Whole skill directories are synced
(`SKILL.md` plus companion files like `references/` and `scripts/`), and
synced names are recorded in a `.ai-config-skills` manifest inside each
provider's skills dir. `--prune` removes only skills recorded in that
manifest, so skills you placed in a provider dir yourself are never
deleted.

A skills lockfile (`.ai-config-lock.json` next to each skills root)
tracks content hashes, `createdAt`/`updatedAt`, and provenance
(`imported:<provider>` for migrated skills, `github:<source>` for skills
installed by the npm `skills` CLI), plus a receipt of the hash last pushed
to each provider. That lets `ai-config status` distinguish a stale copy
from one drifted by local edits, and lets sync back drifted copies up
instead of overwriting them.

```json
{
  "skills": { "enabled": ["skill-a", "skill-b"] },
  "providers": {
    "cursor": { "skills": { "include": ["skill-a"] } },
    "devin": { "skills": { "enabled": false } }
  }
}
```

`skills.enabled` is a global allowlist (empty means all skills are
candidates). `providers.<name>.skills` then narrows per provider:
`include` allowlists, `exclude` removes, and `"enabled": false` opts the
provider out of skill sync entirely - useful when a provider already reads
another location (e.g. Devin scanning `~/.claude/skills`), which would
otherwise list every skill twice.

Same-name skills with different content never land in the store as
`<name>.<provider>` aliases - a folder name that differs from the
SKILL.md `name:` frontmatter cannot load as a skill. Migration quarantines
conflicts under `skill-conflicts/<name>/<provider>/` and records them in
the lockfile; `ai-config migrate --reconcile-aliases` retires aliases left
behind by older versions.

Rules synced into shared files (like a project `AGENTS.md`) are wrapped in
`<!-- BEGIN ai-config managed -->` markers so repeated syncs update in place
without touching the rest of the file.

### `ai-config set-config <provider> <key> <value>`

Set configuration value for a provider.

```bash
ai-config set-config devin model your-model-name
ai-config set-config devin theme_mode dark
```

## Provider Integration

Each AI provider should read from the unified configuration:

```python
from universal_ai_config import UnifiedConfig, AgentEnv

# Initialize
env = AgentEnv()
config = UnifiedConfig(env)

# Get provider-specific config
devin_config = config.get_provider_config("devin")

# Get merged config (user + project)
merged_config = config.get_merged_config(cwd=Path.cwd())
```

## Migration Details

The tool automatically detects and migrates from Devin, Windsurf, Claude,
Cursor, Codex, Gemini, VS Code, Zed, and Continue - see the provider table
above for the exact paths scanned. JSON, TOML, and YAML configs are all
supported.

MCP servers are deduplicated on import: identical entries merge, and a
same-name server with a different config is kept under a `<name>.<provider>`
alias (e.g. `github.cursor`) rather than silently overwriting the existing
one. Skills are deduplicated too: identical skills - and incoming copies
whose files are all identical subsets of the existing skill - are skipped,
while a conflicting same-name skill is quarantined under
`skill-conflicts/<name>/<provider>/` (prompting keep / replace / skip on a
TTY). The whole skill directory, not just `SKILL.md`, is imported. Rules
imports strip managed blocks and dedupe previously migrated chunks; once
the unified `AGENTS.md` holds content it is the master copy, so divergent
provider rules are reported for manual merge instead of appended.

Legacy configs are backed up with `.backup` extension.

## Platform Support

All agent data lives under `~/.agents/` on every platform (Linux, macOS,
Windows). Set the `AGENT_CONFIG_HOME` environment variable to relocate the
base directory.

## Security: Project Configuration

When resolving project configuration, `ai-config` searches parent
directories for `.ai/` folders. **Only `.ai/` directories owned by the
current user are loaded** - this prevents configuration injection from
shared or world-writable workspaces, where another user could plant a
malicious `config.json` or `mcp-config.json` (API keys, MCP servers) that
would merge into your settings and be exported to provider files.

If a `.ai/` directory is skipped, a `SecurityWarning` naming the path is
emitted. On platforms where ownership cannot be verified (Windows), the
config is loaded with a warning instead.

## Best Practices

1. **Secrets Management**: Never store API keys in config files. Use system keyrings or environment variables.

2. **Project Config**: Use `.ai/config.json` for team settings and `.ai/config.local.json` for personal overrides.

3. **Shared Resources**: Put common MCP servers and skills in user config; project-specific ones in `.ai/`.

4. **Validation**: Always run `ai-config validate` after making changes.

## Development

### Setup Development Environment

```bash
git clone https://github.com/DevArtsLab/tool-universal-ai-config.git
cd tool-universal-ai-config
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Format Code

```bash
black universal_ai_config/
```

### Type Check

```bash
mypy universal_ai_config/
```

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please read our contributing guidelines before submitting PRs.

## Support

- GitHub Issues: https://github.com/DevArtsLab/tool-universal-ai-config/issues
- Documentation: https://github.com/DevArtsLab/tool-universal-ai-config/wiki

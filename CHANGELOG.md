# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-27

### Added

- Sync copies whole skill directories, not just `SKILL.md`
- Per-provider skills scoping: `providers.<name>.skills` with `include`,
  `exclude`, or `enabled: false`
- Global `skills.enabled` list honored as a sync allowlist
- `--prune` removes synced skills that left scope, tracked via a
  `.ai-config-skills` manifest so user skills are never deleted
- Symlink mode (default): `ai-config sync` links skill directories into
  provider skills dirs so every provider shares one editable source;
  `--copy` restores copy mode. Provider rules files that hold only the
  unified `AGENTS.md` content are linked the same way
- Skills lockfile `.ai-config-lock.json` next to each skills root: sha256
  content hashes, `createdAt`/`updatedAt` seeded from file mtimes,
  `origin` provenance (`imported:<provider>`, or `github:<source>` for
  skills the npm `skills` CLI installed via its sibling
  `.skill-lock.json`), and per-provider receipts of the last pushed hash.
  Entries drop for skills deleted from disk
- `ai-config status` reports per-provider skill state (in sync, stale,
  drifted, missing) from lockfile receipts and live hashes, plus recorded
  conflicts
- Skill conflict quarantine: a same-name skill with different content
  parks under `skill-conflicts/<name>/<provider>/` (sibling of the skills
  dir) instead of an in-store `<name>.<provider>` alias. On a TTY,
  `migrate` prompts keep / replace / skip; resolved conflicts drop from
  the record once the parked copy is removed
- `ai-config migrate --no-interactive` quarantines without prompting, and
  `--reconcile-aliases` moves legacy `<name>.<provider>` dirs into
  `skill-conflicts/`
- Sync drift protection: a managed provider copy whose live hash differs
  from the recorded push (or predates recording) is backed up, never
  silently overwritten
- Migration subset detection: an incoming skill whose files are all
  identical members of the existing skill is skipped, not conflicted
- OS junk files (`.DS_Store`, `Thumbs.db`, `desktop.ini`, `._*`) are
  ignored by skill hashing and equality so they cannot fabricate drift or
  conflicts
- `ai-config --version`
- CI runs pytest, `black --check`, and `mypy` on every push and PR to main

### Changed

- Unified rules moved to `~/.agents/AGENTS.md`; `init` relocates a legacy
  `config/AGENTS.md` there, and `init --fresh` removes the master rules
  file as well
- Rules migration no longer appends provider text into a populated
  unified `AGENTS.md` - divergence is reported for manual merge, since
  appending is how duplicated lines accumulated
- Windsurf skills sync target is `~/.codeium/windsurf/skills/`; both
  Codeium-era and `~/.windsurf/` skills dirs are still scanned on read

### Fixed

- Conflicting skills can no longer land inside the skills store as
  `<name>.<provider>` dirs that could never load - the skill rule
  requires the folder name to equal the SKILL.md `name:`

- Nested `BEGIN/END ai-config managed` blocks are flattened correctly,
  including text stranded between inner and outer END markers
- Exported rules can no longer carry markers that nest managed blocks
- Rules migration dedupes previously migrated chunks instead of
  compounding duplicated lines on re-import
- `<!-- Migrated from X -->` markers match hyphenated/dotted provider names
- Displaced user skills move to hidden `.ai-config-backups/`; `<name>.backup`
  siblings appeared to providers as phantom skills
- Sync skips rewriting rules files whose managed block is unchanged

## [0.2.1] - 2026-10-05

### Security

- Project config trust checks (CWE-427): `project_config()` and
  `find_project_root()` now skip `.ai/` directories that are not owned by the
  current user, preventing configuration injection (provider credentials,
  MCP servers) from shared or world-writable directories. A
  `SecurityWarning` is emitted when a directory is skipped or when ownership
  cannot be verified (Windows). Directories that fail verification are
  skipped, not loaded.

### Changed

- GitHub Actions bumped to Node 24 majors (`checkout` v7, `setup-python` v7,
  `upload-artifact` v7, `download-artifact` v8, `action-gh-release` v3) -
  clears the Node 20 deprecation annotations on every run.
- Release workflow now derives the GitHub release body from `CHANGELOG.md`
  instead of relying solely on auto-generated notes.

## [0.2.0] - 2026-10-05

### Added

- `ai-config sync` command: writes the unified configuration back to each
  provider's native files (export direction; `migrate` is the import direction)
  - `--dry-run` previews every planned write
  - `--provider <name>` (repeatable) targets specific providers
  - `--all` syncs every known provider, even undetected ones
  - `--project` syncs project-level targets (`.cursor/`, `.vscode/`,
    `.github/copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md`, `.rules`)
  - `--prune` makes provider MCP lists an exact mirror of the unified config,
    backing up files before removing servers
- Per-provider MCP scoping via `providers.<name>.mcp`:
  `{"include": [...]}` or `{"exclude": [...]}`
- Provider coverage expanded from 3 to 9: added Cursor, Codex CLI, Gemini CLI,
  VS Code (Copilot), Zed, and Continue alongside Devin, Windsurf, and Claude
- Multi-format config support: JSON, TOML (`config.toml`), and YAML
  (`config.yaml`) are read and written where providers use them
- Per-provider MCP shape translation: `mcpServers` (most), `servers` with
  `type` (VS Code), `context_servers` (Zed, stdio only), TOML
  `[mcp_servers.*]` (Codex), YAML list (Continue)
- Rules sync: unified `AGENTS.md` lands as a managed block
  (`<!-- BEGIN ai-config managed -->`) in shared files, or as dedicated rule
  files (`.cursor/rules/*.mdc`, `.continue/rules/*.md`, Windsurf global rules)
- Windsurf coverage spans the Codeium-era paths (`~/.codeium/`) and current
  `~/.windsurf/` paths; Devin CLI covers `~/.config/devin/` and `~/.devin/`
- MCP migration dedupes identical servers and keeps conflicting same-name
  servers under a `<name>.<provider>` alias instead of silently overwriting
- `"disabled": true` flag on unified MCP server entries: disabled servers
  stay in the store as dormant inventory and are never exported by sync,
  even when named in a provider's `include` list
- `tests/` suite: 43 tests covering formats, provider translation, sync,
  migration, and project-local config

### Fixed

- `AgentEnv.project_config` was declared `@property` but accepts a `cwd`
  argument, so `get_merged_config(cwd=)` (the documented provider integration
  call) always raised `TypeError`
- `ProjectConfig.enable_feature` overwrote the `enabled_features` list with
  each call, and `disable_feature` wrote to a `disabled_features` key that
  nothing read - both now correctly maintain `enabled_features`
- All outstanding mypy errors in `project.py`, `config.py`, and `migration.py`
- Project local MCP overrides were unusable: `save_mcp_config(local=True)`
  wrote `.ai/mcp-config.local.json` while `get_mcp_config` read
  `.ai/mcp_config.local.json` (and `init-project` gitignored the latter).
  Everything now uses the hyphenated `mcp-config.local.json`
- `ai-config validate` counted skills in `~/.agents/config/skills/` instead
  of the actual `~/.agents/skills/` directory

### Changed

- **BREAKING**: `ai-config sync` no longer writes to every detected provider
  by default. Export is opt-in via `"providers.<name>.sync": true`, or
  explicit `--provider` / `--all` flags. Global config is now the
  store-of-truth; providers read it directly or receive explicit exports.
  This prevents credentials in MCP `env` from propagating to every installed
  tool
- Migration dedupes across provider naming schemes (e.g. VS Code registry
  names like `io.github.X/foo-mcp` match `foo`), normalizes empty injected
  fields on compare, and reuses existing aliases instead of minting `.2`/`.3`
  suffixes on re-import
- `ProviderMigrator.PROVIDER_PATHS` now derives from the provider registry in
  `providers.py` (single source for read paths and sync targets)
- Unified MCP store key renamed to `context_servers` in
  `config/mcp-config.json` and the loaded unified config; the legacy
  `mcpServers` key is still accepted on read
- New dependencies: `tomli` (Python <3.11), `tomli-w`, `pyyaml`

## [0.1.1] - 2026-10-04

### Fixed

- macOS Intel binary build moved from retired `macos-13` runner to
  `macos-15-intel`

## [0.1.0] - 2026-10-04

### Added

- Initial release: `init`, `migrate`, `validate`, `status`, `init-project`,
  `get-config`, `set-config` commands
- Unified `~/.agents/` directory layout and `.ai/` project config
- Migration from Devin, Windsurf, and Claude configs
- PyPI + standalone binary releases via tag-driven workflow

# Threat model: DevArtsLab/tool-universal-ai-config (`ai-config`)

Status: **draft from code**. The user has not answered the threat-model questions yet. Everything below comes from reading the code, so it is not a user decision.

## System overview
`ai-config` is a local Python CLI (`universal_ai_config/cli.py`, entry point `ai-config`) that a developer runs as their own OS user. It keeps one "unified" store under `~/.agents/` (or `$AGENT_CONFIG_HOME`): `config/config.json`, `config/mcp-config.json`, `config/AGENTS.md` and `skills/*/SKILL.md`. It translates that store to and from the native config files of AI coding tools (Claude, Windsurf, Devin, Cursor, Zed, VS Code, Codex, Continue, ... listed in `providers.py` `PROVIDERS`). There is no network service and no server. It ships through PyPI (`.github/workflows/publish.yml`, trusted publishing), PyInstaller binaries on GitHub Releases, and `install.sh`/`uninstall.sh`, which are run with `curl ... | bash`.

## Components
| Name | Covers | Notes |
|---|---|---|
| **CLI** | `universal_ai_config/cli.py`, `__main__.py` | argparse commands `init`, `migrate`, `validate`, `status`, `init-project`, `get-config`, `set-config`, `sync` |
| **Unified store** | `config.py`, `environment.py` | `UnifiedConfig`, `AgentEnv`, precedence and `deep_merge`, `.ai/` ownership trust check (`_trusted_ai_dir`, `find_project_root`) |
| **Project config** | `project.py`, project parts of `environment.py` | Project-local `.ai/` (`config.json`, `config.local.json`, `mcp-config*.json`, `AGENTS.md`, `skills/`) |
| **Sync engine** | `sync.py`, `providers.py`, `formats.py` | Writes provider-native MCP, settings, rules (managed block / `.mdc`) and skills; prune mode; JSON/TOML/YAML I/O (`yaml.safe_load`) |
| **Migration** | `migration.py` | Imports provider configs, MCP servers, skills and rules into the unified store; `migrate --project`, `--all-projects` (globs `~/projects` and `~` up to depth 3) |
| **Installer & release** | `install.sh`, `uninstall.sh`, `.github/workflows/*.yml`, `pyproject.toml` | curl\|bash install, edits `~/.bashrc`/`~/.zshrc`, pip/uv/pipx, PyPI publish, release binaries |

## Trust boundaries
1. **User store (trusted)**: `~/.agents/**`, written only by the user and the tool.
2. **Project `.ai/` and provider project files (semi-trusted / untrusted)**: these come from whatever repository the user has open or has cloned. `get_merged_config` deep-merges project `config.json`/`config.local.json`/`mcp-config*.json` over the user store. `sync --project` then writes their MCP servers (commands that the AI tool will **execute**), rules (instructions the agent follows) and skills into provider files. `migrate --project` / `--all-projects` copy project skills **into the global `~/.agents/skills`**, so content from one repo reaches every project.
3. **Other local users**: on shared machines, `_trusted_ai_dir` / `find_project_root` skip `.ai/` and project roots that the current user doesn't own (CWE-427). On platforms without `os.getuid` (Windows) the check is skipped with a warning.
4. **Provider native files (user-owned, outside the tool)**: the tool reads them during migration and writes them during sync, and it is the AI tools that consume them.
5. **Supply chain**: GitHub repo `main` branch tarball (install.sh), PyPI package, GitHub Actions (`actions/*`, `pypa/gh-action-pypi-publish@release/v1`, `softprops/action-gh-release@v3`), PyInstaller binaries.

## Entry points
- CLI arguments (local user only; `set-config` value is `json.loads`'d).
- Files read: user store, project `.ai/*`, provider native configs (JSON/TOML/YAML), skill and rules files, env vars `AGENT_CONFIG_HOME`, `APPDATA`.
- Files written: `~/.agents/**`, provider configs in `~` and in the project root, `.backup` copies, shell rc files (installer), `~/.local/bin/ai-config` symlink.
- Release pipeline triggers: tag push `v*`, `workflow_dispatch`.

## Assets
- **Secrets in MCP server `env`/`headers`** and in provider configs (API tokens), which are copied between files and stored in plaintext JSON.
- **Integrity of AI-tool configuration**: injected MCP `command`/`args`, permission allow-lists or rules lead to code execution or agent hijack as the user.
- Files under the user's home directory (writes outside the intended paths, overwrite or deletion).
- Integrity of the published package, binaries and install script.

## Attacker profiles (draft)
- **A1 Malicious repository content**: a repo the user clones and runs `ai-config sync --project` / `migrate --project` / `--all-projects` in, or that just sits under `~` within depth 3.
- **A2 Other local user on a shared machine**: plants a `.ai/` or project root in a shared ancestor directory.
- **A3 Supply-chain attacker**: compromise of a CI action, PyPI or the GitHub repo / `main` branch (install.sh downloads `main` unpinned with no checksum).
- Not modeled: remote network attackers (no listening service); the local user themselves.

## Existing controls
- `.ai/` and project-root ownership check (`environment.py` `_trusted_ai_dir`, `find_project_root`).
- Sync is opt-in: only `providers.<name>.sync: true` or explicit `--provider`/`--all` (`sync.py`).
- `yaml.safe_load` / `safe_dump`; TOML via tomllib.
- Disabled MCP servers are never exported; `--dry-run`; a `.backup` is made before a prune.
- PyPI trusted publishing (OIDC `id-token: write`); tag must match the `pyproject` version.

## Out of scope / accepted risk
- None stated by the user yet.

## Open questions
- Is A1 (malicious repo) in scope, or do users only sync trusted repos?
- Are shared multi-user machines (A2) in scope?
- Is the supply chain (A3: install.sh, publish workflow, binaries) in scope?
- Which asset matters most: secrets, or config integrity / code execution?
- No infrastructure repository: it is a local CLI, so none is assumed.

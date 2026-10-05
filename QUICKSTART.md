# Quick Start Guide

## For Users

### New System Installation

```bash
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash
```

This will:

- Download and install the package
- Set up the `ai-config` command
- Initialize the unified config structure
- Add `~/.local/bin` to your PATH if needed

### Existing System Migration

```bash
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash
```

The installer will:

- Detect existing Devin, Windsurf, Claude, Cursor, Codex, Gemini, VS Code,
  Zed, and Continue configs
- Ask if you want to migrate them
- Migrate to the unified structure
- Backup original configs

### Manual Commands

```bash
# Initialize fresh config
ai-config init

# Migrate existing configs
ai-config migrate

# Validate setup
ai-config validate

# Check status
ai-config status

# Initialize project
cd your-project
ai-config init-project

# Get provider config
ai-config get-config devin

# Set provider config
ai-config set-config devin model your-model-name

# Export unified config back to provider-native files
ai-config sync --dry-run            # preview every write
ai-config sync --provider cursor    # one provider, explicit
```

## For Developers

### Integration

```python
from universal_ai_config import UnifiedConfig, AgentEnv
from pathlib import Path

# Initialize
env = AgentEnv()
config = UnifiedConfig(env)

# Get provider config
devin_config = config.get_provider_config("devin")

# Get merged config (user + project)
merged_config = config.get_merged_config(cwd=Path.cwd())
```

See `PROVIDER_INTEGRATION.md` for detailed integration guide.

## Directory Structure

After installation:

```
~/.agents/config/         # User configuration
  ├── config.json         # Unified config
  ├── mcp-config.json     # Shared MCP servers (context_servers key)
  └── AGENTS.md           # Shared rules

~/.agents/skills/         # Shared skills (one dir per skill, each with SKILL.md)

~/.agents/data/           # Persistent data
  ├── memory/             # Long-term memory, datasets
  └── plugins/            # Plugins

~/.agents/state/          # Runtime state
  ├── logs/               # Logs
  └── history/            # Chat history

~/.agents/cache/          # Cache
  ├── models/             # Model caches
  └── venv/               # Isolated environments

.ai/                        # Project config (in repos)
  ├── config.json         # Team settings
  ├── config.local.json   # Personal overrides (gitignored)
  ├── mcp-config.json     # Project MCP servers
  ├── mcp-config.local.json # Personal MCP overrides (gitignored)
  ├── AGENTS.md           # Project rules
  └── skills/             # Project skills
```

## Uninstallation

```bash
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/uninstall.sh | bash
```

## Troubleshooting

### Command not found

Add to your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add to `~/.zshrc` or `~/.bashrc`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Migration issues

```bash
# Check what's detected
ai-config status

# Migrate specific provider
ai-config migrate devin

# Validate after migration
ai-config validate
```

### Clean reinstall

```bash
# Uninstall first
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/uninstall.sh | bash

# Reinstall
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash
```

## Support

- GitHub Issues: https://github.com/DevArtsLab/tool-universal-ai-config/issues
- Documentation: https://github.com/DevArtsLab/tool-universal-ai-config/wiki

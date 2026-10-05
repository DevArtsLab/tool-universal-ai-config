# Provider Integration Guide

This guide explains how AI providers (Devin, Windsurf, Claude, etc.) can integrate with the universal AI configuration system.

## Overview

The universal AI configuration system provides:

- **Single source of truth**: All providers read from `~/.agents/config/config.json`
- **Project-local overrides**: `.ai/config.json` and `.ai/config.local.json` in projects
- **Shared resources**: MCP servers and skills shared across providers
- **Provider-specific overrides**: Each provider can have custom settings

## Integration Steps

### 1. Add Dependency

Add to your provider's `requirements.txt` or `pyproject.toml`:

```bash
pip install universal-ai-config
```

### 2. Read Configuration

```python
from universal_ai_config import UnifiedConfig, AgentEnv
from pathlib import Path

# Initialize
env = AgentEnv()
config = UnifiedConfig(env)

# Get provider-specific configuration
provider_name = "your-provider-name"  # e.g., "devin", "windsurf"
provider_config = config.get_provider_config(provider_name)

# Get merged configuration (user + project)
cwd = Path.cwd()
merged_config = config.get_merged_config(cwd=cwd)
```

### 3. Apply Configuration

Apply the configuration to your provider:

```python
# Example: Apply model setting
model = provider_config.get("model", "default-model")

# Example: Apply permissions
permissions = provider_config.get("permissions", {})
allow_rules = permissions.get("allow", [])
deny_rules = permissions.get("deny", [])
ask_rules = permissions.get("ask", [])

# Example: Apply MCP servers
mcp_servers = provider_config.get("mcpServers", {})
for server_name, server_config in mcp_servers.items():
    # Initialize MCP server with config
    initialize_mcp_server(server_name, server_config)

# Example: Apply skills
skills_config = provider_config.get("skills", {})
enabled_skills = skills_config.get("enabled", [])
skill_paths = skills_config.get("paths", [])
```

### 4. Handle Project-Local Config

Your provider should automatically detect and apply project-local configuration:

```python
def get_effective_config(provider_name: str, cwd: Path) -> dict:
    """Get effective config with project overrides."""
    env = AgentEnv()
    config = UnifiedConfig(env)

    # Start with provider config
    effective_config = config.get_provider_config(provider_name)

    # Merge project config if present
    project_dir = env.project_config(cwd)
    if project_dir:
        project_config_path = project_dir / "config.json"
        if project_config_path.exists():
            project_config = load_json(project_config_path)
            effective_config = deep_merge(effective_config, project_config)

        # Merge local overrides
        project_local_path = project_dir / "config.local.json"
        if project_local_path.exists():
            local_config = load_json(project_local_path)
            effective_config = deep_merge(effective_config, local_config)

    return effective_config
```

## Configuration Structure

### Unified Config Format

The unified config file (`~/.agents/config/config.json`) has this structure:

```json
{
  "shared": {
    // Settings shared by all providers
    "model": "default-model",
    "theme_mode": "dark"
  },
  "providers": {
    "your-provider": {
      // Provider-specific overrides
      "model": "provider-specific-model",
      "permissions": {
        "allow": ["Read(**)", "Exec(git)"],
        "deny": ["Exec(sudo)"],
        "ask": ["Write(**/.env*)"]
      }
    }
  },
  "mcpServers": {
    // Shared MCP servers (stored in ~/.agents/config/mcp-config.json)
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  },
  "skills": {
    // Shared skills configuration
    "enabled": ["skill-name"],
    "paths": ["~/.agents/skills/", ".ai/skills/"]
  }
}
```

### Config Precedence

When reading configuration, use this precedence (highest to lowest):

1. Project local overrides (`.ai/config.local.json`)
2. Project shared config (`.ai/config.json`)
3. Provider-specific settings (in `~/.agents/config/config.json`)
4. Shared settings (in `~/.agents/config/config.json`)

## Migration Support

If your provider has existing configuration, support migration:

```python
# Add a ProviderSpec to the registry in universal_ai_config/providers.py
from universal_ai_config.providers import PROVIDERS, ProviderSpec, SyncTargets

PROVIDERS["your-provider"] = ProviderSpec(
    name="your-provider",
    display="Your Provider",
    detect_paths=["~/.your-provider"],
    read_paths={
        "user_config": ["~/.your-provider/config.json"],
        "user_mcp": ["~/.your-provider/mcp_config.json"],
        "user_skills": ["~/.your-provider/skills/"],
        "user_rules": ["~/.your-provider/AGENTS.md"],
        "project_config": [".your-provider/config.json"],
        "project_mcp": [".your-provider/mcp_config.json"],
        "project_skills": [".your-provider/skills/"],
        "project_rules": ["AGENTS.md"],
    },
    user=SyncTargets(
        config_file="~/.your-provider/config.json",
        mcp_file="~/.your-provider/mcp_config.json",
        mcp_key="mcpServers",
        rules_path="~/.your-provider/AGENTS.md",
        rules_mode="file",
        skills_dir="~/.your-provider/skills",
    ),
)

# Users can then run: ai-config migrate (import) and ai-config sync (export)
```

## Best Practices

### 1. Don't Duplicate Configuration

Don't create your own config files. Read from the unified config.

### 2. Respect Provider Overrides

Always check for provider-specific settings before using shared settings.

### 3. Support Project-Local Config

Automatically detect and apply `.ai/` configuration when in a project.

### 4. Handle Missing Config Gracefully

If the unified config doesn't exist, use sensible defaults:

```python
try:
    config = config.get_provider_config("your-provider")
except ConfigError:
    config = get_default_config()
```

### 5. Document Required Settings

Document which configuration keys your provider supports and their defaults.

## Example Integration

Here's a complete example of integrating a fictional provider:

```python
from universal_ai_config import UnifiedConfig, AgentEnv, ConfigError
from pathlib import Path
import json

class MyAIProvider:
    def __init__(self, cwd: Path = None):
        self.env = AgentEnv()
        self.config = UnifiedConfig(self.env)
        self.cwd = cwd or Path.cwd()
        self.provider_name = "my-provider"
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration with all overrides."""
        try:
            # Get merged config (user + project)
            return self.config.get_merged_config(cwd=self.cwd)
        except ConfigError:
            # Fallback to defaults
            return self._get_defaults()

    def _get_defaults(self) -> dict:
        """Get default configuration."""
        return {
            "model": "default-model",
            "permissions": {
                "allow": ["Read(**)"],
                "deny": [],
                "ask": []
            },
            "mcpServers": {},
            "skills": {
                "enabled": [],
                "paths": []
            }
        }

    @property
    def model(self) -> str:
        """Get the configured model."""
        return self._config.get("model", "default-model")

    @property
    def permissions(self) -> dict:
        """Get permission rules."""
        return self._config.get("permissions", self._get_defaults()["permissions"])

    @property
    def mcp_servers(self) -> dict:
        """Get MCP server configuration."""
        return self._config.get("mcpServers", {})

    def initialize(self):
        """Initialize the provider with loaded configuration."""
        print(f"Initializing {self.provider_name} with model: {self.model}")
        print(f"Permissions: {self.permissions}")
        print(f"MCP servers: {list(self.mcp_servers.keys())}")

        # Initialize MCP servers
        for name, config in self.mcp_servers.items():
            self._init_mcp_server(name, config)

    def _init_mcp_server(self, name: str, config: dict):
        """Initialize an MCP server."""
        print(f"Initializing MCP server: {name}")
        # Your MCP server initialization logic here
```

## Testing

Test your integration with the CLI:

```bash
# Initialize unified config
ai-config init

# Add your provider config
ai-config set-config my-provider model my-model

# Verify
ai-config get-config my-provider

# Test project-local config
cd your-project
ai-config init-project
ai-config set-config my-provider model project-model
```

## Support

For integration issues:

- GitHub Issues: https://github.com/DevArtsLab/tool-universal-ai-config/issues
- Documentation: https://github.com/DevArtsLab/tool-universal-ai-config/wiki

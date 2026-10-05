# Installation Guide

## Prerequisites

- Python 3.9 or higher
- pip (Python package manager)

## Installation Methods

### Method 1: Install from PyPI (Recommended)

```bash
pip install universal-ai-config
```

This will install the `ai-config` command-line tool globally.

### Method 2: Install from Source

```bash
# Clone the repository
git clone https://github.com/DevArtsLab/tool-universal-ai-config.git
cd tool-universal-ai-config

# Install in development mode
pip install -e .

# Or install normally
pip install .
```

### Method 3: Install with pipx (Isolated Environment)

```bash
pipx install universal-ai-config
```

## Verification

After installation, verify it's working:

```bash
ai-config --help
```

You should see the help output with all available commands.

## Quick Start

### For New Users

```bash
# Initialize global configuration
ai-config init

# Initialize for a project
cd your-project
ai-config init-project

# Verify setup
ai-config validate
```

### For Existing Users (Migration)

```bash
# Migrate all existing provider configs
ai-config migrate

# Migrate project-specific configs
cd your-project
ai-config migrate --project

# Verify migration
ai-config validate
ai-config status
```

## Uninstallation

```bash
pip uninstall universal-ai-config
```

Note: This will not remove your configuration files. To remove those:

```bash
# Remove global config
rm -rf ~/.agents/config/
rm -rf ~/.agents/data/
rm -rf ~/.agents/state/
rm -rf ~/.agents/cache/

# Remove project configs (per project)
rm -rf .ai/
```

## Platform-Specific Notes

### Linux

Uses XDG Base Directory Specification by default:

- Config: `~/.agents/config/`
- Data: `~/.agents/data/`
- State: `~/.agents/state/`
- Cache: `~/.agents/cache/`

### macOS

Same as Linux (XDG-compliant):

- Config: `~/.agents/config/`
- Data: `~/.agents/data/`
- State: `~/.agents/state/`
- Cache: `~/.agents/cache/`

### Windows

Uses the same `~/.agents/` layout (`%USERPROFILE%\.agents\`):

- Config: `%USERPROFILE%\.agents\config\`
- Data: `%USERPROFILE%\.agents\data\`
- State: `%USERPROFILE%\.agents\state\`
- Cache: `%USERPROFILE%\.agents\cache\`

On all platforms, `AGENT_CONFIG_HOME` overrides the base directory.

## Troubleshooting

### Command not found

If `ai-config` command is not found after installation:

```bash
# Check if pip bin directory is in PATH
python -m site --user-base

# Add the bin directory to your PATH
# On Linux/macOS: export PATH="$PATH:$(python -m site --user-base)/bin"
# On Windows: Add %USERPROFILE%\AppData\Roaming\Python\Scripts to PATH
```

### Permission errors

If you encounter permission errors:

```bash
# Install to user directory
pip install --user universal-ai-config

# Or use a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install universal-ai-config
```

### Migration issues

If migration fails:

```bash
# Check what providers are detected
ai-config status

# Migrate specific provider individually
ai-config migrate devin

# Validate after migration
ai-config validate
```

## Development Installation

For contributors:

```bash
git clone https://github.com/DevArtsLab/tool-universal-ai-config.git
cd tool-universal-ai-config
pip install -e ".[dev]"
```

This installs the package in development mode with additional dev dependencies (pytest, black, mypy).

"""
Format-aware config file I/O.

Supports JSON, TOML, and YAML based on file extension.
TOML reading uses stdlib tomllib on Python 3.11+, tomli on older versions.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


class FormatError(Exception):
    """Config format errors."""

    pass


def detect_format(path: Path) -> str:
    """Detect config format from file extension."""
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return "toml"
    if suffix in (".yaml", ".yml"):
        return "yaml"
    if suffix == ".json":
        return "json"
    raise FormatError(f"Unknown config format for {path}")


def load_any(path: Path) -> Dict[str, Any]:
    """Load a JSON, TOML, or YAML file as a dict."""
    fmt = detect_format(path)
    try:
        if fmt == "toml":
            with open(path, "rb") as f:
                toml_data: Dict[str, Any] = tomllib.load(f)
                return toml_data
        with open(path, "r") as f:
            if fmt == "yaml":
                if yaml is None:
                    raise FormatError("PyYAML is required for YAML configs")
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
            json_data: Dict[str, Any] = json.load(f)
            return json_data
    except FormatError:
        raise
    except Exception as e:
        raise FormatError(f"Invalid {fmt.upper()} in {path}: {e}")


def load_any_safe(path: Path) -> Dict[str, Any]:
    """Load a config file, returning {} on any error or missing file."""
    if not path or not path.exists() or not path.is_file():
        return {}
    try:
        return load_any(path)
    except FormatError:
        return {}


def save_any(path: Path, data: Dict[str, Any]) -> None:
    """Save a dict as JSON, TOML, or YAML based on file extension."""
    fmt = detect_format(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "toml":
        if tomli_w is None:
            raise FormatError("tomli-w is required to write TOML configs")
        with open(path, "wb") as f:
            tomli_w.dump(data, f)
    elif fmt == "yaml":
        if yaml is None:
            raise FormatError("PyYAML is required to write YAML configs")
        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    else:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

"""Tests for multi-format config I/O."""

import pytest
from pathlib import Path

from universal_ai_config.formats import (
    detect_format,
    load_any,
    load_any_safe,
    save_any,
    FormatError,
)


def test_detect_format(tmp_path):
    assert detect_format(Path("a.json")) == "json"
    assert detect_format(Path("a.toml")) == "toml"
    assert detect_format(Path("a.yaml")) == "yaml"
    assert detect_format(Path("a.yml")) == "yaml"
    with pytest.raises(FormatError):
        detect_format(Path("a.ini"))


def test_json_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    save_any(p, {"mcpServers": {"x": {"command": "npx"}}})
    assert load_any(p) == {"mcpServers": {"x": {"command": "npx"}}}


def test_toml_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    data = {"model": "gpt-5", "mcp_servers": {"gh": {"command": "npx", "args": ["-y", "x"]}}}
    save_any(p, data)
    assert load_any(p) == data


def test_yaml_roundtrip(tmp_path):
    p = tmp_path / "config.yaml"
    data = {"mcpServers": [{"name": "gh", "command": "npx"}]}
    save_any(p, data)
    assert load_any(p) == data


def test_load_any_safe_missing(tmp_path):
    assert load_any_safe(tmp_path / "nope.json") == {}


def test_load_any_safe_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load_any_safe(p) == {}

"""Tests for the provider registry and MCP shape translation."""

from universal_ai_config.providers import (
    PROVIDERS,
    render_mcp_servers,
    extract_mcp_servers,
    detect_installed,
)

SERVERS = {
    "github": {"command": "npx", "args": ["-y", "gh-mcp"], "env": {"K": "v"}},
    "remote": {"url": "https://mcp.example.com", "headers": {"A": "b"}},
}


def test_registry_covers_expected_providers():
    for name in (
        "devin",
        "windsurf",
        "claude",
        "cursor",
        "codex",
        "gemini",
        "vscode",
        "zed",
        "continue",
    ):
        assert name in PROVIDERS


def test_render_map_passthrough():
    assert render_mcp_servers("map", SERVERS) == SERVERS


def test_render_vscode_adds_type():
    out = render_mcp_servers("vscode", SERVERS)
    assert out["github"]["type"] == "stdio"
    assert out["remote"]["type"] == "http"


def test_render_zed_transforms_stdio_and_drops_remote():
    out = render_mcp_servers("zed", SERVERS)
    assert out["github"]["command"]["path"] == "npx"
    assert out["github"]["command"]["args"] == ["-y", "gh-mcp"]
    assert "remote" not in out  # Zed settings.json supports stdio only


def test_render_list():
    out = render_mcp_servers("list", SERVERS)
    assert isinstance(out, list)
    names = {s["name"] for s in out}
    assert names == {"github", "remote"}


def test_extract_standard():
    spec = PROVIDERS["cursor"]
    data = {"mcpServers": {"gh": {"command": "npx"}}}
    assert extract_mcp_servers(spec, data) == {"gh": {"command": "npx"}}


def test_extract_vscode_strips_type():
    spec = PROVIDERS["vscode"]
    data = {"servers": {"gh": {"type": "stdio", "command": "npx"}}}
    assert extract_mcp_servers(spec, data) == {"gh": {"command": "npx"}}


def test_extract_zed_untransforms():
    spec = PROVIDERS["zed"]
    data = {"context_servers": {"gh": {"command": {"path": "npx", "args": ["x"], "env": {}}}}}
    # empty env is normalized away so round-trips compare equal
    assert extract_mcp_servers(spec, data) == {"gh": {"command": "npx", "args": ["x"]}}


def test_extract_list_style():
    spec = PROVIDERS["continue"]
    data = {"mcpServers": [{"name": "gh", "command": "npx", "args": []}]}
    # empty args is normalized away
    assert extract_mcp_servers(spec, data) == {"gh": {"command": "npx"}}


def test_extract_toml_style():
    spec = PROVIDERS["codex"]
    data = {"mcp_servers": {"gh": {"command": "npx"}}}
    assert extract_mcp_servers(spec, data) == {"gh": {"command": "npx"}}

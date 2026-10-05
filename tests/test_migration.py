"""Tests for provider migration, including MCP duplicate handling."""

import json
import pytest

from universal_ai_config.config import UnifiedConfig
from universal_ai_config.environment import AgentEnv
from universal_ai_config.migration import ProviderMigrator


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENT_CONFIG_HOME", str(home / ".agents"))
    env = AgentEnv()
    env.initialize_dirs()
    config = UnifiedConfig(env)
    config.save_unified(
        {"shared": {}, "providers": {}, "skills": {"enabled": [], "paths": []}}
    )
    return home


def _write_cursor_mcp(home, servers):
    cursor = home / ".cursor"
    cursor.mkdir(exist_ok=True)
    (cursor / "mcp.json").write_text(json.dumps({"mcpServers": servers}))


def test_migrate_imports_cursor_mcp(sandbox):
    _write_cursor_mcp(sandbox, {"gh": {"command": "npx", "args": ["x"]}})
    ProviderMigrator(AgentEnv()).migrate_provider("cursor")
    assert UnifiedConfig(AgentEnv()).load_mcp_servers()["gh"]["command"] == "npx"


def test_migrate_dedupes_identical_server(sandbox, capsys):
    config = UnifiedConfig(AgentEnv())
    config.add_mcp_server("gh", {"command": "npx", "args": ["x"]})
    _write_cursor_mcp(sandbox, {"gh": {"command": "npx", "args": ["x"]}})

    ProviderMigrator(AgentEnv()).migrate_provider("cursor")

    out = capsys.readouterr().out
    assert "duplicate" in out.lower()
    assert len(UnifiedConfig(AgentEnv()).load_mcp_servers()) == 1


def test_migrate_conflict_keeps_both_under_alias(sandbox):
    config = UnifiedConfig(AgentEnv())
    config.add_mcp_server("gh", {"command": "original"})
    _write_cursor_mcp(sandbox, {"gh": {"command": "different"}})

    ProviderMigrator(AgentEnv()).migrate_provider("cursor")

    servers = UnifiedConfig(AgentEnv()).load_mcp_servers()
    assert servers["gh"]["command"] == "original"
    assert servers["gh.cursor"]["command"] == "different"


def test_migrate_zed_context_servers(sandbox):
    zed = sandbox / ".config" / "zed"
    zed.mkdir(parents=True)
    (zed / "settings.json").write_text(
        json.dumps(
            {
                "context_servers": {
                    "fs": {"command": {"path": "fs-mcp", "args": ["--root", "/tmp"], "env": {}}}
                }
            }
        )
    )

    ProviderMigrator(AgentEnv()).migrate_provider("zed")

    servers = UnifiedConfig(AgentEnv()).load_mcp_servers()
    assert servers["fs"] == {"command": "fs-mcp", "args": ["--root", "/tmp"], "env": {}}


def test_detect_providers_includes_new_ones(sandbox):
    (sandbox / ".cursor").mkdir()
    (sandbox / ".cursor" / "mcp.json").write_text("{}")
    (sandbox / ".codex").mkdir()
    (sandbox / ".codex" / "config.toml").write_text('model = "x"\n')

    detected = ProviderMigrator(AgentEnv()).detect_providers()
    assert "cursor" in detected
    assert "codex" in detected

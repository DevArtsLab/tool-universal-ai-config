"""Tests for the sync engine (unified -> provider-native write-out)."""

import json
import pytest
from pathlib import Path

from universal_ai_config.config import UnifiedConfig
from universal_ai_config.environment import AgentEnv
from universal_ai_config.sync import SyncEngine, BLOCK_BEGIN, BLOCK_END


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolated HOME + AGENT_CONFIG_HOME so sync never touches real dirs."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENT_CONFIG_HOME", str(home / ".agents"))

    env = AgentEnv()
    env.initialize_dirs()

    config = UnifiedConfig(env)
    config.save_unified(
        {
            "shared": {},
            "providers": {"cursor": {"chat.fontSize": 14}},
            "skills": {"enabled": [], "paths": []},
        }
    )
    config.save_mcp_servers(
        {
            "github": {"command": "npx", "args": ["-y", "gh-mcp"]},
        }
    )
    (env.config / "AGENTS.md").write_text("# Rules\n\nBe nice.\n")
    skill = env.skills / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n")

    return home


def test_sync_cursor_writes_native_files(sandbox):
    (sandbox / ".cursor").mkdir()  # provider "installed"
    engine = SyncEngine(AgentEnv())
    result = engine.sync(providers=["cursor"])

    mcp = json.loads((sandbox / ".cursor" / "mcp.json").read_text())
    assert mcp["mcpServers"]["github"]["command"] == "npx"

    settings = json.loads((sandbox / ".cursor" / "settings.json").read_text())
    assert settings["chat.fontSize"] == 14

    rule = sandbox / ".cursor" / "rules" / "ai-config.mdc"
    assert rule.exists()
    assert "alwaysApply: true" in rule.read_text()
    assert "Be nice." in rule.read_text()

    assert (sandbox / ".cursor" / "skills" / "demo-skill" / "SKILL.md").exists()
    assert any(a.status == "written" for a in result.actions)


def test_sync_dry_run_writes_nothing(sandbox):
    (sandbox / ".cursor").mkdir()
    engine = SyncEngine(AgentEnv())
    result = engine.sync(providers=["cursor"], dry_run=True)

    assert result.actions
    assert all(a.status == "planned" for a in result.actions)
    assert not (sandbox / ".cursor" / "mcp.json").exists()


def test_sync_claude_rules_managed_block(sandbox):
    (sandbox / ".claude").mkdir()
    target = sandbox / ".claude" / "CLAUDE.md"
    target.write_text("# Existing notes\n")

    engine = SyncEngine(AgentEnv())
    engine.sync(providers=["claude"])

    text = target.read_text()
    assert "# Existing notes" in text
    assert BLOCK_BEGIN in text and "Be nice." in text

    # Second sync replaces the block rather than duplicating it
    engine.sync(providers=["claude"])
    assert target.read_text().count(BLOCK_BEGIN) == 1


def test_sync_codex_toml(sandbox):
    (sandbox / ".codex").mkdir()
    engine = SyncEngine(AgentEnv())
    engine.sync(providers=["codex"])

    import tomllib

    data = tomllib.loads((sandbox / ".codex" / "config.toml").read_text())
    assert data["mcp_servers"]["github"]["command"] == "npx"
    assert (sandbox / ".codex" / "AGENTS.md").exists()


def test_sync_continue_yaml_list(sandbox):
    (sandbox / ".continue").mkdir()
    engine = SyncEngine(AgentEnv())
    engine.sync(providers=["continue"])

    import yaml

    data = yaml.safe_load((sandbox / ".continue" / "config.yaml").read_text())
    servers = data["mcpServers"]
    assert isinstance(servers, list)
    assert servers[0]["name"] == "github"


def test_sync_zed_context_servers(sandbox):
    (sandbox / ".config" / "zed").mkdir(parents=True)
    engine = SyncEngine(AgentEnv())
    engine.sync(providers=["zed"])

    data = json.loads((sandbox / ".config" / "zed" / "settings.json").read_text())
    assert data["context_servers"]["github"]["command"]["path"] == "npx"


def test_sync_project_scope(tmp_path, sandbox, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    monkeypatch.chdir(proj)

    engine = SyncEngine(AgentEnv())
    result = engine.sync(providers=["claude", "vscode"], project=True)

    assert (proj / ".mcp.json").exists()
    mcp = json.loads((proj / ".vscode" / "mcp.json").read_text())
    assert mcp["servers"]["github"]["type"] == "stdio"
    assert (proj / "CLAUDE.md").exists()
    assert (proj / ".github" / "copilot-instructions.md").exists()


def test_sync_unknown_provider(sandbox):
    engine = SyncEngine(AgentEnv())
    result = engine.sync(providers=["nonexistent"])
    assert result.actions[0].status == "error"


def test_sync_mcp_scoping_include(sandbox):
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"include": ["github"]}}}
    config.save_unified(unified)
    config.save_mcp_servers({"github": {"command": "a"}, "other": {"command": "b"}})

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    mcp = json.loads((sandbox / ".cursor" / "mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"github"}


def test_sync_mcp_scoping_exclude(sandbox):
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"exclude": ["other"]}}}
    config.save_unified(unified)
    config.save_mcp_servers({"github": {"command": "a"}, "other": {"command": "b"}})

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    mcp = json.loads((sandbox / ".cursor" / "mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"github"}


def test_sync_prune_removes_extra_servers(sandbox):
    (sandbox / ".cursor").mkdir()
    mcp_path = sandbox / ".cursor" / "mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": {"stale": {"command": "old"}}}))

    engine = SyncEngine(AgentEnv())
    engine.sync(providers=["cursor"], prune=True)

    mcp = json.loads(mcp_path.read_text())
    assert "stale" not in mcp["mcpServers"]
    assert "github" in mcp["mcpServers"]
    assert (sandbox / ".cursor" / "mcp.json.backup").exists()


def test_sync_without_prune_keeps_extra_servers(sandbox):
    (sandbox / ".cursor").mkdir()
    mcp_path = sandbox / ".cursor" / "mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": {"stale": {"command": "old"}}}))

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    mcp = json.loads(mcp_path.read_text())
    assert "stale" in mcp["mcpServers"]
    assert "github" in mcp["mcpServers"]
    assert not (sandbox / ".cursor" / "mcp.json.backup").exists()


def test_sync_prune_dry_run_reports_removal(sandbox):
    (sandbox / ".cursor").mkdir()
    mcp_path = sandbox / ".cursor" / "mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": {"stale": {"command": "old"}}}))

    result = SyncEngine(AgentEnv()).sync(providers=["cursor"], prune=True, dry_run=True)

    assert any("stale" in a.detail for a in result.actions)
    assert json.loads(mcp_path.read_text())["mcpServers"]["stale"]


def test_detect_installed_in_sandbox(sandbox):
    from universal_ai_config.providers import detect_installed

    (sandbox / ".cursor").mkdir()
    assert "cursor" in detect_installed()
    assert "zed" not in detect_installed()


def test_bare_sync_writes_nothing_without_optin(sandbox):
    """Detected-but-not-opted-in providers get no writes by default."""
    (sandbox / ".cursor").mkdir()
    result = SyncEngine(AgentEnv()).sync()

    assert not result.actions
    assert not (sandbox / ".cursor" / "mcp.json").exists()


def test_bare_sync_writes_opted_in_providers(sandbox):
    (sandbox / ".cursor").mkdir()
    (sandbox / ".codex").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"sync": True}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync()

    assert (sandbox / ".cursor" / "mcp.json").exists()
    assert not (sandbox / ".codex" / "config.toml").exists()

"""Tests for the sync engine (unified -> provider-native write-out)."""

import json
import shutil
import pytest
from pathlib import Path

try:
    import tomllib as _tomllib
except ImportError:  # Python < 3.11
    import tomli as _tomllib

from universal_ai_config.config import UnifiedConfig
from universal_ai_config.environment import AgentEnv
from universal_ai_config.sync import (
    SyncEngine,
    BLOCK_BEGIN,
    BLOCK_END,
    SKILLS_BACKUP_DIR,
    strip_managed_markers,
)


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
            # MCP export is fail-closed: tests that exercise write mechanics
            # opt each provider in wholesale via "include": ["*"].
            "providers": {
                name: {"mcp": {"include": ["*"]}}
                for name in ("cursor", "claude", "codex", "continue", "zed", "vscode")
            }
            | {"cursor": {"chat.fontSize": 14, "mcp": {"include": ["*"]}}},
            "skills": {"enabled": [], "paths": []},
        }
    )
    config.save_mcp_servers(
        {
            "github": {"command": "npx", "args": ["-y", "gh-mcp"]},
        }
    )
    (env.rules).write_text("# Rules\n\nBe nice.\n")
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

    data = _tomllib.loads((sandbox / ".codex" / "config.toml").read_text())
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
    """exclude subtracts from the include grant."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"include": ["*"], "exclude": ["other"]}}}
    config.save_unified(unified)
    config.save_mcp_servers({"github": {"command": "a"}, "other": {"command": "b"}})

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    mcp = json.loads((sandbox / ".cursor" / "mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"github"}


def test_sync_mcp_unscoped_exports_nothing(sandbox):
    """Fail-closed: a provider with no mcp scope gets no servers at all."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert not (sandbox / ".cursor" / "mcp.json").exists()


def test_sync_mcp_exclude_alone_grants_nothing(sandbox):
    """exclude on its own grants nothing - only include exports."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"exclude": ["other"]}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert not (sandbox / ".cursor" / "mcp.json").exists()


def test_sync_mcp_empty_include_prune_wipes_servers(sandbox):
    """include: [] grants nothing; --prune mirrors that onto the file."""
    (sandbox / ".cursor").mkdir()
    mcp_path = sandbox / ".cursor" / "mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": {"stale": {"command": "old"}}}))
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"include": []}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"], prune=True)

    mcp = json.loads(mcp_path.read_text())
    assert mcp["mcpServers"] == {}


def test_sync_skips_disabled_servers(sandbox):
    """Entries flagged disabled are dormant inventory: never exported."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    config.save_mcp_servers(
        {
            "github": {"command": "a"},
            "dormant": {"command": "b", "disabled": True},
        }
    )

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    mcp = json.loads((sandbox / ".cursor" / "mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"github"}


def test_sync_disabled_wins_over_include(sandbox):
    """A disabled server is not exported even when named in include."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"include": ["github", "dormant"]}}}
    config.save_unified(unified)
    config.save_mcp_servers(
        {
            "github": {"command": "a"},
            "dormant": {"command": "b", "disabled": True},
        }
    )

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


def test_sync_cleans_nested_managed_blocks(sandbox):
    """A rules file corrupted by nested managed blocks is flattened to one."""
    (sandbox / ".claude").mkdir()
    target = sandbox / ".claude" / "CLAUDE.md"
    target.write_text(
        "# head\n" f"{BLOCK_BEGIN}\nold outer\n{BLOCK_BEGIN}\nnested\n{BLOCK_END}\n{BLOCK_END}\n"
    )

    SyncEngine(AgentEnv()).sync(providers=["claude"])

    text = target.read_text()
    assert text.count(BLOCK_BEGIN) == 1
    assert text.count(BLOCK_END) == 1
    assert "old outer" not in text and "nested" not in text
    assert "# head" in text


def test_sync_cleans_nested_blocks_with_interstitial_text(sandbox):
    """Text between an inner END and the outer END is part of the nested
    block and must not survive as residue."""
    (sandbox / ".claude").mkdir()
    target = sandbox / ".claude" / "CLAUDE.md"
    target.write_text(
        "# head\n"
        f"{BLOCK_BEGIN}\nouter\n{BLOCK_BEGIN}\ninner\n{BLOCK_END}\nresidue\n{BLOCK_END}\n"
    )

    SyncEngine(AgentEnv()).sync(providers=["claude"])

    text = target.read_text()
    assert text.count(BLOCK_BEGIN) == 1
    assert text.count(BLOCK_END) == 1
    assert "outer" not in text and "inner" not in text and "residue" not in text
    assert "# head" in text


def test_strip_managed_markers_unclosed_begin_keeps_content():
    """An unclosed BEGIN drops only the marker, not the text after it."""
    text = strip_managed_markers(f"# head\n{BLOCK_BEGIN}\norphaned content\n")
    assert "orphaned content" in text
    assert "# head" in text
    assert BLOCK_BEGIN not in text and BLOCK_END not in text


def test_sync_skips_unchanged_rules(sandbox):
    """A second sync reports rules as skipped instead of rewriting them."""
    (sandbox / ".claude").mkdir()
    engine = SyncEngine(AgentEnv())
    engine.sync(providers=["claude"])
    before = (sandbox / ".claude" / "CLAUDE.md").stat().st_mtime_ns

    result = engine.sync(providers=["claude"])

    rules = [a for a in result.actions if a.kind == "rules"]
    assert rules and all(a.status == "skipped" for a in rules)
    assert (sandbox / ".claude" / "CLAUDE.md").stat().st_mtime_ns == before


def test_sync_never_exports_markers_inside_block(sandbox):
    """Markers in the unified rules text are stripped before wrapping."""
    (sandbox / ".claude").mkdir()
    config = UnifiedConfig(AgentEnv())
    (config.env.rules).write_text(f"# Rules\n\n{BLOCK_BEGIN}\nsneaky\n{BLOCK_END}\n\nBe nice.\n")
    target = sandbox / ".claude" / "CLAUDE.md"

    SyncEngine(AgentEnv()).sync(providers=["claude"])

    text = target.read_text()
    assert text.count(BLOCK_BEGIN) == 1
    assert text.count(BLOCK_END) == 1
    assert "sneaky" not in text
    assert "Be nice." in text


def test_sync_skills_copies_companion_files(sandbox):
    """Whole skill directories are linked, not just SKILL.md."""
    (sandbox / ".cursor").mkdir()
    skill = AgentEnv().skills / "demo-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "references" / "deep.md").write_text("# Deep\n")

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    target = sandbox / ".cursor" / "skills" / "demo-skill"
    assert (target / "SKILL.md").exists()
    assert (target / "references" / "deep.md").read_text() == "# Deep\n"


def test_sync_skills_scoping_include(sandbox):
    (sandbox / ".cursor").mkdir()
    (AgentEnv().skills / "other-skill").mkdir()
    (AgentEnv().skills / "other-skill" / "SKILL.md").write_text("# Other\n")
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"skills": {"include": ["demo-skill"]}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert (sandbox / ".cursor" / "skills" / "demo-skill").exists()
    assert not (sandbox / ".cursor" / "skills" / "other-skill").exists()


def test_sync_skills_scoping_exclude(sandbox):
    (sandbox / ".cursor").mkdir()
    (AgentEnv().skills / "other-skill").mkdir()
    (AgentEnv().skills / "other-skill" / "SKILL.md").write_text("# Other\n")
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"skills": {"exclude": ["other-skill"]}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert (sandbox / ".cursor" / "skills" / "demo-skill").exists()
    assert not (sandbox / ".cursor" / "skills" / "other-skill").exists()


def test_sync_skills_never_syncs_migration_aliases(sandbox):
    """name.<provider> dirs are migration artifacts; they stay local."""
    (sandbox / ".cursor").mkdir()
    for alias in ("demo-skill.cursor", "demo-skill.devin.2"):
        d = AgentEnv().skills / alias
        d.mkdir()
        (d / "SKILL.md").write_text("# Variant\n")

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    skills = sandbox / ".cursor" / "skills"
    assert (skills / "demo-skill" / "SKILL.md").exists()
    assert not (skills / "demo-skill.cursor").exists()
    assert not (skills / "demo-skill.devin.2").exists()
    assert "cursor" not in (skills / ".ai-config-skills").read_text()


def test_sync_skills_provider_disabled(sandbox):
    """providers.<name>.skills.enabled: false opts out of skills sync."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"skills": {"enabled": False}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert not (sandbox / ".cursor" / "skills").exists()


def test_sync_skills_global_enabled_allowlist(sandbox):
    """A non-empty skills.enabled list limits which skills sync at all."""
    (sandbox / ".cursor").mkdir()
    (AgentEnv().skills / "other-skill").mkdir()
    (AgentEnv().skills / "other-skill" / "SKILL.md").write_text("# Other\n")
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["skills"] = {"enabled": ["demo-skill"], "paths": []}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert (sandbox / ".cursor" / "skills" / "demo-skill").exists()
    assert not (sandbox / ".cursor" / "skills" / "other-skill").exists()


def test_sync_skills_prune_removes_only_managed(sandbox):
    """--prune removes skills ai-config previously synced but never user dirs."""
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"])

    target = sandbox / ".cursor" / "skills"
    assert (target / "demo-skill").exists()
    (target / "user-skill").mkdir()  # never managed by ai-config
    (target / "user-skill" / "SKILL.md").write_text("# Mine\n")
    shutil.rmtree(env.skills / "demo-skill")  # dropped from unified set

    SyncEngine(env).sync(providers=["cursor"], prune=True)

    assert not (target / "demo-skill").exists()
    assert (target / "user-skill" / "SKILL.md").exists()


def test_sync_skills_without_prune_keeps_stale(sandbox):
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"])
    shutil.rmtree(env.skills / "demo-skill")

    SyncEngine(env).sync(providers=["cursor"])

    # The link object survives without prune even though its target is gone.
    assert (sandbox / ".cursor" / "skills" / "demo-skill").is_symlink()


def test_sync_skills_preserves_unmanaged_collision(sandbox):
    """A user-managed same-named dir is backed up, never destroyed."""
    (sandbox / ".cursor").mkdir()
    skills = sandbox / ".cursor" / "skills"
    target = skills / "demo-skill"
    (target / "references").mkdir(parents=True)
    (target / "SKILL.md").write_text("# User's own version\n")
    (target / "references" / "mine.md").write_text("precious\n")

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert (target / "SKILL.md").read_text() == "# Demo\n"  # synced copy wins the name
    backup = skills / SKILLS_BACKUP_DIR / "demo-skill"
    assert (backup / "references" / "mine.md").read_text() == "precious\n"
    # Backups live a level deeper in a hidden dir, so nothing at the top
    # level of the skills dir can be discovered as a phantom skill.
    assert not (skills / "demo-skill.backup").exists()
    assert SyncEngine._list_skill_names(skills) == ["demo-skill"]
    assert "demo-skill" in (skills / ".ai-config-skills").read_text()


def test_sync_skills_replaces_managed_dir(sandbox):
    """A managed link replaced by a real dir holding local edits drifts from
    the recorded push: it is backed up rather than silently deleted, then
    relinked wholesale."""
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"])
    target = sandbox / ".cursor" / "skills" / "demo-skill"
    target.unlink()
    target.mkdir()
    (target / "SKILL.md").write_text("# Demo\n")
    (target / "user-added.md").write_text("mine\n")

    SyncEngine(env).sync(providers=["cursor"])

    assert not (target / "user-added.md").exists()
    backup = sandbox / ".cursor" / "skills" / SKILLS_BACKUP_DIR / "demo-skill"
    assert (backup / "user-added.md").read_text() == "mine\n"


def test_sync_skills_backs_up_stray_file(sandbox):
    """A file (not a dir) at an unmanaged skill path is preserved."""
    (sandbox / ".cursor").mkdir()
    skills = sandbox / ".cursor" / "skills"
    skills.mkdir(parents=True)
    (skills / "demo-skill").write_text("stray file\n")

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert (skills / "demo-skill" / "SKILL.md").exists()
    assert (skills / SKILLS_BACKUP_DIR / "demo-skill").read_text() == "stray file\n"


def test_sync_skills_unlinks_file_at_managed_path(sandbox):
    """A file left at a managed path is unlinked, not rmtree'd."""
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"])
    skills = sandbox / ".cursor" / "skills"
    (skills / "demo-skill").unlink()
    (skills / "demo-skill").write_text("stray\n")

    SyncEngine(env).sync(providers=["cursor"])

    assert (skills / "demo-skill" / "SKILL.md").exists()
    assert not (skills / SKILLS_BACKUP_DIR).exists()


def test_sync_skills_empty_scope_creates_nothing(sandbox):
    """When scoping excludes every skill, no dir or manifest is created."""
    (sandbox / ".cursor").mkdir()
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"skills": {"exclude": ["demo-skill"]}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    assert not (sandbox / ".cursor" / "skills").exists()


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
    unified["providers"] = {"cursor": {"sync": True, "mcp": {"include": ["*"]}}}
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync()

    assert (sandbox / ".cursor" / "mcp.json").exists()
    assert not (sandbox / ".codex" / "config.toml").exists()


def test_sync_skills_symlinks_by_default(sandbox):
    """User-scope sync links provider skills to the unified source."""
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"])

    target = sandbox / ".cursor" / "skills" / "demo-skill"
    assert target.is_symlink()
    assert target.resolve() == (env.skills / "demo-skill").resolve()
    assert (target / "SKILL.md").read_text() == "# Demo\n"


def test_sync_skills_symlink_failure_is_error(sandbox, monkeypatch):
    """Link-only: a failed symlink is a loud error, never a silent copy."""
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()

    def no_link(self, target, target_is_directory=False):
        raise OSError("symlink not permitted")

    monkeypatch.setattr(Path, "symlink_to", no_link)
    result = SyncEngine(env).sync(providers=["cursor"])

    target = sandbox / ".cursor" / "skills" / "demo-skill"
    assert not target.exists() and not target.is_symlink()
    errors = [a for a in result.actions if a.status == "error"]
    assert any("symlink failed" in a.detail for a in errors)


def test_sync_skills_relinks_drifted_real_dir(sandbox):
    """A real dir at the managed path (no recorded drift) that matches source
    is simply relinked; a divergent one is backed up first."""
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    skills = sandbox / ".cursor" / "skills"
    (skills / "demo-skill" / "references").mkdir(parents=True)
    (skills / "demo-skill" / "SKILL.md").write_text("# My own version\n")

    SyncEngine(env).sync(providers=["cursor"])

    target = skills / "demo-skill"
    assert target.is_symlink()
    assert (skills / SKILLS_BACKUP_DIR / "demo-skill" / "SKILL.md").read_text() == (
        "# My own version\n"
    )


def test_sync_rules_links_user_rules_file(sandbox):
    """file-mode providers get a symlink to the unified rules file."""
    (sandbox / ".claude").mkdir()
    env = AgentEnv()
    (env.rules).write_text("# Rules\n\n- Be nice.\n")
    SyncEngine(env).sync(providers=["claude"])

    target = sandbox / ".claude" / "CLAUDE.md"
    assert target.is_symlink()
    assert target.resolve() == env.rules.resolve()


def test_sync_rules_unmanaged_content_keeps_managed_block(sandbox):
    """A rules file with unmanaged content gets the managed block, not a link."""
    claude = sandbox / ".claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("# My own notes\n")
    env = AgentEnv()
    (env.rules).write_text("# Rules\n\n- Be nice.\n")
    SyncEngine(env).sync(providers=["claude"])

    target = claude / "CLAUDE.md"
    assert not target.is_symlink()
    text = target.read_text()
    assert "My own notes" in text
    assert "Be nice." in text


def test_sync_rules_never_writes_through_link_to_unified(sandbox):
    """A provider rules file linked to the unified file must never be
    written through - even when the unified content stops being linkable
    (e.g. it picked up managed markers), the master file is untouched."""
    claude = sandbox / ".claude"
    claude.mkdir()
    env = AgentEnv()
    (env.rules).write_text(f"# Rules\n\n{BLOCK_BEGIN}\nold junk\n{BLOCK_END}\n")
    target = claude / "CLAUDE.md"
    target.symlink_to(env.rules.resolve())

    before = (env.rules).read_text()
    SyncEngine(env).sync(providers=["claude"])

    assert (env.rules).read_text() == before
    assert not target.is_symlink()


def test_sync_rules_user_symlink_content_preserved(sandbox):
    """A rules file that is a symlink to the user's own document keeps its
    content: the link becomes a real file holding that text plus the
    managed block, and the original target is untouched."""
    claude = sandbox / ".claude"
    claude.mkdir()
    mine = sandbox / "myrules.md"
    mine.write_text("# My own rules\n")
    target = claude / "CLAUDE.md"
    target.symlink_to(mine.resolve())
    env = AgentEnv()
    (env.rules).write_text("# Rules\n\n- Be nice.\n")

    SyncEngine(env).sync(providers=["claude"])

    assert mine.read_text() == "# My own rules\n"
    assert not target.is_symlink()
    text = target.read_text()
    assert "My own rules" in text
    assert "Be nice." in text


def test_sync_rules_link_failure_writes_managed_block(sandbox, monkeypatch):
    """When symlink creation is impossible, rules fall back to the managed
    block rather than failing."""
    (sandbox / ".claude").mkdir()
    env = AgentEnv()
    (env.rules).write_text("# Rules\n\n- Be nice.\n")

    def boom(self, *args, **kwargs):
        raise OSError("privilege not held")

    monkeypatch.setattr(Path, "symlink_to", boom)
    SyncEngine(env).sync(providers=["claude"])

    target = sandbox / ".claude" / "CLAUDE.md"
    assert not target.is_symlink()
    assert "Be nice." in target.read_text()


def test_sync_skills_include_and_exclude_combine(sandbox):
    """include grants, then exclude subtracts - same semantics as MCP."""
    (sandbox / ".cursor").mkdir()
    other = AgentEnv().skills / "other-skill"
    other.mkdir()
    (other / "SKILL.md").write_text("# Other\n")
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {
        "cursor": {"skills": {"include": ["demo-skill", "other-skill"], "exclude": ["demo-skill"]}}
    }
    config.save_unified(unified)

    SyncEngine(AgentEnv()).sync(providers=["cursor"])

    skills = sandbox / ".cursor" / "skills"
    assert not (skills / "demo-skill").exists()
    assert (skills / "other-skill").exists()


def test_sync_skills_failed_relink_keeps_existing_target(sandbox, monkeypatch):
    """A failed symlink must leave the existing provider skill in place:
    the link is staged beside the target and only renamed in after the
    old path is displaced."""
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    skills = sandbox / ".cursor" / "skills"
    target = skills / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Provider-local version\n")

    def boom(self, *args, **kwargs):
        raise OSError("privilege not held")

    monkeypatch.setattr(Path, "symlink_to", boom)
    result = SyncEngine(env).sync(providers=["cursor"])

    assert (target / "SKILL.md").read_text() == "# Provider-local version\n"
    assert not target.is_symlink()
    assert not (skills / ".demo-skill.ai-config-link").exists()
    errors = [a for a in result.actions if a.status == "error"]
    assert any("symlink failed" in a.detail for a in errors)

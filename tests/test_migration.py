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
    config.save_unified({"shared": {}, "providers": {}, "skills": {"enabled": [], "paths": []}})
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


def test_migrate_seeds_mcp_include(sandbox):
    """Migration seeds providers.<name>.mcp.include from the servers the
    provider actually had, so a later sync keeps exactly that set."""
    _write_cursor_mcp(sandbox, {"gh": {"command": "a"}, "fs": {"command": "b"}})

    ProviderMigrator(AgentEnv()).migrate_provider("cursor")

    conf = UnifiedConfig(AgentEnv()).load_unified(include_mcp=False)
    assert conf["providers"]["cursor"]["mcp"]["include"] == ["fs", "gh"]


def test_migrate_seed_uses_alias_names(sandbox):
    """When the provider's server collides and lands under an alias, the
    seeded include names the alias - the name the provider's variant
    actually holds in the unified store."""
    config = UnifiedConfig(AgentEnv())
    config.add_mcp_server("gh", {"command": "other"})
    _write_cursor_mcp(sandbox, {"gh": {"command": "mine"}})

    ProviderMigrator(AgentEnv()).migrate_provider("cursor")

    conf = UnifiedConfig(AgentEnv()).load_unified(include_mcp=False)
    assert conf["providers"]["cursor"]["mcp"]["include"] == ["gh.cursor"]


def test_migrate_does_not_clobber_mcp_scope(sandbox):
    """A hand-set mcp scope survives a re-migration."""
    config = UnifiedConfig(AgentEnv())
    unified = config.load_unified(include_mcp=False)
    unified["providers"] = {"cursor": {"mcp": {"include": ["only-this"]}}}
    config.save_unified(unified)
    _write_cursor_mcp(sandbox, {"gh": {"command": "a"}})

    ProviderMigrator(AgentEnv()).migrate_provider("cursor")

    conf = UnifiedConfig(AgentEnv()).load_unified(include_mcp=False)
    assert conf["providers"]["cursor"]["mcp"]["include"] == ["only-this"]


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
    assert servers["fs"] == {"command": "fs-mcp", "args": ["--root", "/tmp"]}


def test_zed_roundtrip_no_false_conflict(sandbox, capsys):
    """A server synced out to zed and re-imported must dedupe, not alias."""
    config = UnifiedConfig(AgentEnv())
    config.add_mcp_server("cdt", {"command": "npx", "args": ["-y", "x"]})

    zed = sandbox / ".config" / "zed"
    zed.mkdir(parents=True)
    # zed-native shape as written by sync: env:{} injected, settings wrapper
    (zed / "settings.json").write_text(
        json.dumps(
            {
                "context_servers": {
                    "cdt": {
                        "command": {"path": "npx", "args": ["-y", "x"], "env": {}},
                        "settings": {},
                    }
                }
            }
        )
    )

    ProviderMigrator(AgentEnv()).migrate_provider("zed")

    out = capsys.readouterr().out
    assert "duplicate" in out.lower()
    servers = UnifiedConfig(AgentEnv()).load_mcp_servers()
    assert "cdt.zed" not in servers
    assert list(servers) == ["cdt"]


def test_vscode_registry_name_dedupes(sandbox, capsys):
    """io.github.X/foo-mcp style names match a unified 'foo' entry."""
    config = UnifiedConfig(AgentEnv())
    config.add_mcp_server("github-mcp-server", {"command": "npx", "args": ["gh"]})

    vsc = sandbox / "vscdir"
    vsc.mkdir()
    (vsc / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "io.github.github/github-mcp-server": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["gh"],
                    }
                }
            }
        )
    )

    original = ProviderMigrator.PROVIDER_PATHS["vscode"]
    ProviderMigrator.PROVIDER_PATHS["vscode"] = {"user_mcp": [str(vsc / "mcp.json")]}
    try:
        ProviderMigrator(AgentEnv()).migrate_provider("vscode")
    finally:
        ProviderMigrator.PROVIDER_PATHS["vscode"] = original

    out = capsys.readouterr().out
    assert "duplicate" in out.lower()
    servers = UnifiedConfig(AgentEnv()).load_mcp_servers()
    assert "io.github.github/github-mcp-server" not in servers
    assert len(servers) == 1


def _write_claude_skill(home, name="my-skill", body="# Skill\n", extra=None):
    skills = home / ".claude" / "skills" / name
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "SKILL.md").write_text(body)
    for rel, content in (extra or {}).items():
        f = skills / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    return skills


def test_migrate_skills_dedupes_identical(sandbox, capsys):
    env = AgentEnv()
    src = _write_claude_skill(sandbox)
    ProviderMigrator(env).migrate_provider("claude")

    capsys.readouterr()
    ProviderMigrator(env).migrate_provider("claude")

    out = capsys.readouterr().out
    assert "Skipping duplicate skill: my-skill" in out
    assert (env.skills / "my-skill" / "SKILL.md").read_text() == "# Skill\n"


def test_migrate_skill_conflict_quarantined(sandbox):
    """A conflicting provider skill never becomes a '<name>.<provider>'
    folder inside the store: folder name must match frontmatter name.
    The incoming copy is copied to skill-conflicts/, provider keeps its
    own, and the lock records the conflict."""
    env = AgentEnv()
    existing = env.skills / "my-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("---\nname: my-skill\n---\n# Original\n")
    _write_claude_skill(sandbox, body="---\nname: my-skill\n---\n# Different\n")

    ProviderMigrator(env, interactive=False).migrate_provider("claude")

    assert not (env.skills / "my-skill.claude").exists()
    assert (env.skills / "my-skill" / "SKILL.md").read_text().endswith("# Original\n")
    held = env.base / "skill-conflicts" / "my-skill" / "claude" / "SKILL.md"
    assert held.read_text().endswith("# Different\n")
    # The provider's own copy is untouched.
    assert (
        (sandbox / ".claude" / "skills" / "my-skill" / "SKILL.md")
        .read_text()
        .endswith("# Different\n")
    )
    from universal_ai_config.lockfile import SkillsLock

    lock = SkillsLock(env.base)
    conflicts = lock.data["conflicts"]["my-skill"]
    assert conflicts[-1]["resolution"] == "kept-existing"
    assert conflicts[-1]["provider"] == "claude"


def test_migrate_skill_conflict_replace(sandbox, monkeypatch):
    """Interactive 'replace' quarantines the existing unified copy and
    imports the provider copy under the real name."""
    env = AgentEnv()
    existing = env.skills / "my-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# Original\n")
    _write_claude_skill(sandbox, body="# Different\n")

    monkeypatch.setattr("builtins.input", lambda _: "r")
    ProviderMigrator(env, interactive=True).migrate_provider("claude")

    assert (env.skills / "my-skill" / "SKILL.md").read_text() == "# Different\n"
    held = env.base / "skill-conflicts" / "my-skill" / "unified" / "SKILL.md"
    assert held.read_text() == "# Original\n"


def test_migrate_skill_conflict_skip(sandbox, monkeypatch):
    """Interactive 'skip' imports nothing and quarantines nothing."""
    env = AgentEnv()
    existing = env.skills / "my-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# Original\n")
    _write_claude_skill(sandbox, body="# Different\n")

    monkeypatch.setattr("builtins.input", lambda _: "s")
    ProviderMigrator(env, interactive=True).migrate_provider("claude")

    assert (env.skills / "my-skill" / "SKILL.md").read_text() == "# Original\n"
    assert not (env.base / "skill-conflicts").exists()


def test_migrate_skill_subset_skips_quietly(sandbox, capsys):
    """A provider copy holding a strict subset of the unified skill is a
    duplicate, not a conflict: identical SKILL.md, missing companion files."""
    env = AgentEnv()
    existing = env.skills / "my-skill"
    (existing / "references").mkdir(parents=True)
    (existing / "SKILL.md").write_text("---\nname: my-skill\n---\n# Full\n")
    (existing / "references" / "deep.md").write_text("# Deep\n")
    _write_claude_skill(sandbox, body="---\nname: my-skill\n---\n# Full\n")

    ProviderMigrator(env, interactive=False).migrate_provider("claude")

    out = capsys.readouterr().out
    assert "Skipping subset skill: my-skill" in out
    assert not (env.base / "skill-conflicts").exists()


def test_migrate_skill_ignores_ds_store(sandbox, capsys):
    """.DS_Store and AppleDouble files never count toward equality."""
    env = AgentEnv()
    existing = env.skills / "my-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# Skill\n")
    (existing / ".DS_Store").write_bytes(b"junk-a")
    src = _write_claude_skill(sandbox)
    (src / "._SKILL.md").write_bytes(b"junk-b")

    ProviderMigrator(env, interactive=False).migrate_provider("claude")

    out = capsys.readouterr().out
    assert "Skipping duplicate skill: my-skill" in out
    assert not (env.base / "skill-conflicts").exists()


def test_reconcile_skill_aliases(sandbox):
    """Legacy '<name>.<provider>' dirs move to skill-conflicts/ verbatim."""
    env = AgentEnv()
    base = env.skills / "my-skill"
    base.mkdir(parents=True)
    (base / "SKILL.md").write_text("---\nname: my-skill\n---\n# Unified\n")
    for prov in ("claude", "cursor", "claude.2"):
        d = env.skills / f"my-skill.{prov}"
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: my-skill\n---\n# {prov}\n")

    moved = ProviderMigrator(env, interactive=False).reconcile_skill_aliases(env.skills)

    assert moved == 3
    assert [x.name for x in env.skills.iterdir() if x.is_dir()] == ["my-skill"]
    assert (
        (env.base / "skill-conflicts" / "my-skill" / "claude" / "SKILL.md")
        .read_text()
        .endswith("# claude\n")
    )
    assert (env.base / "skill-conflicts" / "my-skill" / "cursor" / "SKILL.md").exists()
    assert (env.base / "skill-conflicts" / "my-skill" / "claude.2" / "SKILL.md").exists()


def test_reconcile_skill_aliases_dotted_name(sandbox):
    """'foo.bar.claude' splits at the provider suffix: base 'foo.bar',
    provider 'claude' - not base 'foo' with tag 'bar.claude'."""
    env = AgentEnv()
    d = env.skills / "foo.bar.claude"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: foo.bar\n---\n")

    moved = ProviderMigrator(env, interactive=False).reconcile_skill_aliases(env.skills)

    assert moved == 1
    assert (env.base / "skill-conflicts" / "foo.bar" / "claude" / "SKILL.md").exists()
    assert not (env.base / "skill-conflicts" / "foo").exists()


def test_migrate_skill_copies_companion_files(sandbox):
    env = AgentEnv()
    _write_claude_skill(sandbox, extra={"references/deep.md": "# Deep\n"})

    ProviderMigrator(env).migrate_provider("claude")

    assert (env.skills / "my-skill" / "references" / "deep.md").read_text() == "# Deep\n"


def test_migrate_rules_dedupes_migrated_chunks(sandbox):
    """A provider file carrying previously migrated copies does not grow the
    unified rules file."""
    env = AgentEnv()
    rules = "# Global Rules\n\n- Be nice.\n"
    claude = sandbox / ".claude"
    (claude / "skills").mkdir(parents=True)  # marks provider as present
    # File contains the same rules twice, as left by an earlier migration.
    (claude / "CLAUDE.md").write_text(rules + "\n<!-- Migrated from devin -->\n" + rules)

    ProviderMigrator(env).migrate_provider("claude")

    unified = (env.rules).read_text()
    assert unified.count("Be nice.") == 1


def test_migrate_rules_strips_managed_blocks_on_reimport(sandbox):
    """An existing unified rules file is the master: provider content,
    managed or not, is never appended into it."""
    from universal_ai_config.sync import BLOCK_BEGIN, BLOCK_END

    env = AgentEnv()
    rules = "# Global Rules\n\n- Be nice.\n"
    claude = sandbox / ".claude"
    (claude / "skills").mkdir(parents=True)
    (env.rules).write_text(rules)
    # Simulate a file after sync: managed block wrapping the same rules.
    (claude / "CLAUDE.md").write_text(f"# Custom\n\n{BLOCK_BEGIN}\n{rules}{BLOCK_END}\n")

    ProviderMigrator(env).migrate_provider("claude")

    unified = (env.rules).read_text()
    assert unified == rules
    assert BLOCK_BEGIN not in unified


def test_migrate_skills_ignores_nested_skill_md(sandbox):
    """A SKILL.md inside a skill's companion dirs is not a separate skill."""
    env = AgentEnv()
    _write_claude_skill(sandbox, extra={"examples/demo/SKILL.md": "# Nested\n"})

    ProviderMigrator(env).migrate_provider("claude")

    nested = env.skills / "my-skill" / "examples" / "demo" / "SKILL.md"
    assert nested.read_text() == "# Nested\n"
    assert not (env.skills / "demo").exists()


def test_migrate_rules_keeps_substring_chunk(sandbox):
    """A distinct chunk that is a substring of an earlier chunk is kept when
    seeding a missing unified rules file."""
    env = AgentEnv()
    claude = sandbox / ".claude"
    (claude / "skills").mkdir(parents=True)  # marks provider as present
    # "- Be nice." is a substring of "- Be nice. Always." but is new content.
    (claude / "CLAUDE.md").write_text(
        "- Be nice. Always.\n<!-- Migrated from cursor -->\n- Be nice.\n"
    )

    ProviderMigrator(env).migrate_provider("claude")

    unified = (env.rules).read_text()
    assert "Be nice. Always." in unified
    assert unified.count("Be nice") == 2


def test_detect_providers_includes_new_ones(sandbox):
    (sandbox / ".cursor").mkdir()
    (sandbox / ".cursor" / "mcp.json").write_text("{}")
    (sandbox / ".codex").mkdir()
    (sandbox / ".codex" / "config.toml").write_text('model = "x"\n')

    detected = ProviderMigrator(AgentEnv()).detect_providers()
    assert "cursor" in detected
    assert "codex" in detected


def test_migrate_project_resolves_against_project_root(sandbox, tmp_path, monkeypatch):
    """Provider project paths are relative to the project, not the CWD."""
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    (project / ".devin").mkdir()
    (project / ".devin" / "config.json").write_text('{"x": 1}')
    monkeypatch.chdir(tmp_path)  # CWD deliberately outside the project

    ProviderMigrator(AgentEnv()).migrate_project(project)

    assert (project / ".agents" / "config.json").exists()


def test_migrate_stray_file_at_skill_path_moved_aside(sandbox):
    """A non-directory blocking a skill's path is parked in
    skill-conflicts/, not crashed on or deleted."""
    env = AgentEnv()
    stray = env.skills / "demo"
    stray.write_text("junk")
    src = sandbox / "provider-skills"
    incoming = src / "demo"
    incoming.mkdir(parents=True)
    (incoming / "SKILL.md").write_text("# Demo\n")

    count = ProviderMigrator(env)._import_skills_dir(src, env.skills, "devin")

    assert count == 1
    assert (env.skills / "demo" / "SKILL.md").is_file()
    assert (env.base / "skill-conflicts" / "demo" / "stray").is_file()

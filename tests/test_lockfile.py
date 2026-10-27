"""Tests for the skills lockfile and lock-aware sync behavior."""

import json
import pytest
from pathlib import Path

from universal_ai_config.config import UnifiedConfig
from universal_ai_config.environment import AgentEnv
from universal_ai_config.lockfile import LOCK_NAME, SkillsLock, dir_hash
from universal_ai_config.sync import SKILLS_BACKUP_DIR, SyncEngine


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
            "providers": {"cursor": {}},
            "skills": {"enabled": [], "paths": []},
        }
    )
    (env.rules).write_text("# Rules\n")
    skill = env.skills / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n")

    return home


def test_dir_hash_stable_and_sensitive(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "SKILL.md").write_text("# A\n")
    (a / "ref.txt").write_text("x")
    b = tmp_path / "b"
    b.mkdir()
    (b / "SKILL.md").write_text("# A\n")
    (b / "ref.txt").write_text("x")

    assert dir_hash(a) == dir_hash(b)

    (b / "ref.txt").write_text("y")
    assert dir_hash(a) != dir_hash(b)


def test_lock_records_created_and_updated(tmp_path):
    lock = SkillsLock(tmp_path)
    lock.record_source("skill-a", "hash-1")
    entry = lock.data["skills"]["skill-a"]
    assert entry["hash"] == "hash-1"
    assert "createdAt" in entry
    assert "updatedAt" in entry

    # Same hash: no timestamp churn.
    entry.pop("updatedAt")
    lock.record_source("skill-a", "hash-1")
    assert "updatedAt" not in lock.data["skills"]["skill-a"]

    lock.record_source("skill-a", "hash-2")
    assert lock.data["skills"]["skill-a"]["hash"] == "hash-2"
    assert "updatedAt" in lock.data["skills"]["skill-a"]


def test_lock_round_trip(tmp_path):
    lock = SkillsLock(tmp_path)
    lock.record_source("skill-a", "h1", origin="imported:claude")
    lock.record_sync("cursor", "skill-a", "h1")
    lock.save()

    reloaded = SkillsLock(tmp_path)
    assert reloaded.source_hash("skill-a") == "h1"
    assert reloaded.data["skills"]["skill-a"]["origin"] == "imported:claude"
    assert reloaded.provider_hash("cursor", "skill-a") == "h1"

    reloaded.forget_sync("cursor", "skill-a")
    assert reloaded.provider_hash("cursor", "skill-a") is None


def test_lock_prunes_gone_conflicts(tmp_path):
    lock = SkillsLock(tmp_path)
    parked = tmp_path / "skill-conflicts" / "x" / "claude"
    parked.mkdir(parents=True)
    lock.record_conflict("x", "claude", str(parked), "kept-existing")
    lock.record_conflict("y", "cursor", str(tmp_path / "gone"), "kept-existing")
    lock.record_conflict("z", "devin", None, "skipped")

    assert lock.prune_conflicts() == 1
    assert list(lock.data["conflicts"]) == ["x", "z"]

    parked.rmdir()
    (tmp_path / "skill-conflicts" / "x").rmdir()
    (tmp_path / "skill-conflicts").rmdir()
    assert lock.prune_conflicts() == 1
    assert list(lock.data["conflicts"]) == ["z"]


def test_sync_writes_lock(sandbox):
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"])

    lock_path = env.base / LOCK_NAME
    assert lock_path.is_file()
    lock = SkillsLock(env.base)

    src_hash = dir_hash(env.skills / "demo-skill")
    assert lock.source_hash("demo-skill") == src_hash
    assert lock.provider_hash("cursor", "demo-skill") == src_hash
    entry = lock.data["skills"]["demo-skill"]
    assert "createdAt" in entry and "updatedAt" in entry
    synced = lock.data["providers"]["cursor"]["skills"]["demo-skill"]
    assert "syncedAt" in synced


def test_sync_backs_up_drifted_managed_copy(sandbox):
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    engine = SyncEngine(env)
    engine.sync(providers=["cursor"])

    # Drift under link mode: replace the managed symlink with a real dir
    # holding local edits, then bump the source.
    target = sandbox / ".cursor" / "skills" / "demo-skill"
    target.unlink()
    target.mkdir()
    (target / "SKILL.md").write_text("# Locally edited\n")
    (env.skills / "demo-skill" / "SKILL.md").write_text("# Demo v2\n")

    engine.sync(providers=["cursor"])

    backups = sandbox / ".cursor" / "skills" / SKILLS_BACKUP_DIR
    assert (backups / "demo-skill" / "SKILL.md").read_text() == "# Locally edited\n"
    assert (target / "SKILL.md").read_text() == "# Demo v2\n"

    lock = SkillsLock(env.base)
    assert lock.provider_hash("cursor", "demo-skill") == dir_hash(env.skills / "demo-skill")


def test_sync_overwrites_undrifted_managed_copy(sandbox):
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    engine = SyncEngine(env)
    engine.sync(providers=["cursor"])

    # Source changes only: provider copy is untouched, no backup needed.
    (env.skills / "demo-skill" / "SKILL.md").write_text("# Demo v2\n")
    engine.sync(providers=["cursor"])

    backups = sandbox / ".cursor" / "skills" / SKILLS_BACKUP_DIR
    assert not backups.exists()
    assert (sandbox / ".cursor" / "skills" / "demo-skill" / "SKILL.md").read_text() == "# Demo v2\n"


def test_dry_run_writes_no_lock(sandbox):
    (sandbox / ".cursor").mkdir()
    env = AgentEnv()
    SyncEngine(env).sync(providers=["cursor"], dry_run=True)
    assert not (env.base / LOCK_NAME).exists()

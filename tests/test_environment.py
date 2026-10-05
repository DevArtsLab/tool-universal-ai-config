"""Tests for directory-ownership trust checks (CWE-427 remediation)."""

import os
import pytest
from pathlib import Path

from universal_ai_config.environment import (
    AgentEnv,
    SecurityWarning,
    find_project_root,
)


@pytest.fixture
def owned_project(tmp_path):
    """A .ai/ project dir owned by the current user."""
    proj = tmp_path / "proj"
    (proj / ".ai").mkdir(parents=True)
    return proj


def _as_other_user(monkeypatch):
    """Make every directory look foreign-owned to the trust checks."""
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)


def test_project_config_accepts_user_owned(owned_project):
    env = AgentEnv()
    assert env.project_config(cwd=owned_project) == owned_project / ".ai"


def test_project_config_from_nested_subdir(owned_project):
    nested = owned_project / "src" / "pkg"
    nested.mkdir(parents=True)
    env = AgentEnv()
    assert env.project_config(cwd=nested) == owned_project / ".ai"


def test_project_config_rejects_foreign_owned(owned_project, monkeypatch):
    _as_other_user(monkeypatch)
    env = AgentEnv()
    with pytest.warns(SecurityWarning, match="not owned by the current user"):
        assert env.project_config(cwd=owned_project) is None


def test_project_config_warns_and_loads_when_unverifiable(owned_project, monkeypatch):
    monkeypatch.delattr(os, "getuid")
    env = AgentEnv()
    with pytest.warns(SecurityWarning, match="Cannot verify ownership"):
        assert env.project_config(cwd=owned_project) == owned_project / ".ai"


def test_project_config_none_when_no_ai(tmp_path):
    env = AgentEnv()
    assert env.project_config(cwd=tmp_path) is None


def test_find_project_root_accepts_owned_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert find_project_root(cwd=repo) == repo


def test_find_project_root_accepts_owned_ai(owned_project):
    assert find_project_root(cwd=owned_project) == owned_project


def test_find_project_root_rejects_foreign_ai(owned_project, monkeypatch):
    _as_other_user(monkeypatch)
    with pytest.warns(SecurityWarning):
        assert find_project_root(cwd=owned_project) is None


def test_find_project_root_rejects_foreign_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _as_other_user(monkeypatch)
    with pytest.warns(SecurityWarning, match="untrusted project root"):
        assert find_project_root(cwd=repo) is None


def test_config_precedence_excludes_untrusted(owned_project, monkeypatch):
    (owned_project / ".ai" / "config.json").write_text("{}")
    _as_other_user(monkeypatch)
    env = AgentEnv()
    with pytest.warns(SecurityWarning):
        precedence = env.get_config_precedence(cwd=owned_project)
    assert owned_project / ".ai" / "config.json" not in precedence

"""Tests for project-local (.ai/) configuration management."""

from universal_ai_config.project import ProjectConfig


def _project(tmp_path):
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    return ProjectConfig(project_root=tmp_path)


def test_local_mcp_round_trip(tmp_path):
    """save_mcp_config(local=True) must land in the file get_mcp_config reads."""
    pc = _project(tmp_path)
    pc.add_mcp_server("local-srv", {"command": "run"}, local=True)

    assert (tmp_path / ".ai" / "mcp-config.local.json").exists()
    merged = pc.get_mcp_config()
    assert merged["mcpServers"]["local-srv"]["command"] == "run"


def test_shared_and_local_mcp_merge(tmp_path):
    pc = _project(tmp_path)
    pc.add_mcp_server("shared-srv", {"command": "a"})
    pc.add_mcp_server("local-srv", {"command": "b"}, local=True)

    merged = pc.get_mcp_config()
    assert set(merged["mcpServers"]) == {"shared-srv", "local-srv"}

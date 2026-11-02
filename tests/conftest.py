import pytest

from universal_ai_config import sync as sync_module


@pytest.fixture(autouse=True)
def _skip_admin_gate(monkeypatch):
    """Most tests exercise sync logic, not the sudo gate: bypass it."""
    monkeypatch.setattr(sync_module, "_require_admin", lambda: None)

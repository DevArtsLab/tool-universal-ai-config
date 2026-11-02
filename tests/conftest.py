import pytest

from universal_ai_config import sync as sync_module


@pytest.fixture(autouse=True)
def _admin_verified(monkeypatch):
    """Most tests exercise sync logic, not the sudo gate: treat it as passed."""
    monkeypatch.setattr(sync_module, "_admin_verified", True)

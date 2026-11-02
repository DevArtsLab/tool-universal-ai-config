"""Tests for the sync admin gate in cli.py."""

import os
import sys
from unittest.mock import patch

import pytest

from universal_ai_config.cli import require_admin_for_sync


def _posix():
    return patch.object(os, "name", "posix")


def test_non_root_exits_and_notifies():
    with _posix(), patch.object(os, "geteuid", return_value=501), patch(
        "universal_ai_config.cli._notify_sync_attempt"
    ) as notify, pytest.raises(SystemExit) as exc:
        require_admin_for_sync()
    assert exc.value.code == 1
    notify.assert_called_once()


def test_non_posix_exits():
    with patch.object(os, "name", "nt"), pytest.raises(SystemExit):
        require_admin_for_sync()


def test_root_drops_to_sudo_user():
    with _posix(), patch.object(os, "geteuid", return_value=0), patch.dict(
        os.environ, {"SUDO_UID": "501", "SUDO_GID": "20"}
    ), patch.object(os, "setgid") as setgid, patch.object(os, "setuid") as setuid:
        require_admin_for_sync()
    setgid.assert_called_once_with(20)
    setuid.assert_called_once_with(501)


def test_root_without_sudo_env_warns_and_stays_root(capsys):
    env = {k: v for k, v in os.environ.items() if k not in ("SUDO_UID", "SUDO_GID")}
    with _posix(), patch.object(os, "geteuid", return_value=0), patch.dict(
        os.environ, env, clear=True
    ), patch.object(os, "setuid") as setuid:
        require_admin_for_sync()
    setuid.assert_not_called()
    assert "SUDO_UID" in capsys.readouterr().out


def test_root_with_partial_sudo_env_stays_root():
    with _posix(), patch.object(os, "geteuid", return_value=0), patch.dict(
        os.environ, {"SUDO_UID": "501", "SUDO_GID": ""}
    ), patch.object(os, "setuid") as setuid:
        require_admin_for_sync()
    setuid.assert_not_called()

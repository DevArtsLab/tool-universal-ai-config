"""
Skills lockfile: a JSON record of skill content hashes and sync history.

One lock lives next to each skills root (``~/.agents/.ai-config-lock.json``
for the unified store, ``<project>/.ai/.ai-config-lock.json`` for project
scopes). It mirrors the shape of the npm ``skills`` CLI lockfile
(``.skill-lock.json``) but is a separate file owned by ai-config.

Two sections:

- ``skills``: unified-store facts per skill - content ``hash``,
  ``createdAt``/``updatedAt`` timestamps, optional ``origin``
  (e.g. ``imported:claude``). Lets SKILL.md files drop hand-maintained
  "last updated" comments.
- ``providers``: per-provider receipts - what hash was last pushed where,
  and when. Comparing a provider copy's live hash against the recorded
  hash detects local drift; comparing it against the current source hash
  detects stale copies.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOCK_NAME = ".ai-config-lock.json"
LOCK_VERSION = 1


def dir_hash(path: Path) -> str:
    """Content fingerprint of a directory: sha256 over sorted
    (relative path, file bytes) pairs. Stable across mtime/mode noise."""
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode() + b"\0")
            h.update(p.read_bytes() + b"\0")
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SkillsLock:
    """Read/write access to one skills lockfile."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / LOCK_NAME
        self.data: Dict[str, Any] = {
            "version": LOCK_VERSION,
            "skills": {},
            "providers": {},
            "conflicts": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            loaded = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(loaded, dict):
            loaded.setdefault("version", LOCK_VERSION)
            loaded.setdefault("skills", {})
            loaded.setdefault("providers", {})
            loaded.setdefault("conflicts", {})
            self.data = loaded

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    # ---- unified-store section ----

    def record_source(self, name: str, content_hash: str, origin: Optional[str] = None) -> None:
        """Register the current unified-store hash for a skill. Sets
        createdAt on first sight; bumps updatedAt whenever the hash moves."""
        entry = self.data["skills"].get(name)
        if entry is None:
            entry = {"createdAt": _now()}
            self.data["skills"][name] = entry
        if entry.get("hash") != content_hash:
            entry["hash"] = content_hash
            entry["updatedAt"] = _now()
        if origin:
            entry["origin"] = origin

    def source_hash(self, name: str) -> Optional[str]:
        entry = self.data["skills"].get(name)
        return entry.get("hash") if isinstance(entry, dict) else None

    # ---- provider section ----

    def record_sync(self, provider: str, name: str, content_hash: str) -> None:
        """Record that content_hash was pushed to provider for skill name."""
        prov = self.data["providers"].setdefault(provider, {"skills": {}})
        prov.setdefault("skills", {})[name] = {"hash": content_hash, "syncedAt": _now()}

    def provider_hash(self, provider: str, name: str) -> Optional[str]:
        """Hash last pushed to provider, or None if never recorded."""
        prov = self.data["providers"].get(provider, {})
        entry = prov.get("skills", {}).get(name)
        return entry.get("hash") if isinstance(entry, dict) else None

    def forget_sync(self, provider: str, name: str) -> None:
        """Drop a provider receipt, e.g. after --prune removes the copy."""
        skills = self.data["providers"].get(provider, {}).get("skills", {})
        skills.pop(name, None)

    # ---- conflict section ----

    def record_conflict(
        self, name: str, provider: str, quarantined_to: Optional[str], resolution: str
    ) -> None:
        """Log a same-name skill conflict. quarantined_to is where the losing
        copy was parked (None when nothing was moved). Entries accumulate as
        a list so repeated conflicts stay visible until resolved on disk."""
        entry = {
            "provider": provider,
            "resolution": resolution,
            "at": _now(),
        }
        if quarantined_to:
            entry["quarantinedTo"] = quarantined_to
        self.data["conflicts"].setdefault(name, []).append(entry)

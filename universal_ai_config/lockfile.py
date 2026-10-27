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
NPM_LOCK_NAME = ".skill-lock.json"  # sibling file owned by the npm skills CLI
LOCK_VERSION = 1

# Files that carry no skill content but differ constantly on disk (Finder
# droppings, Windows thumbnails). They must not count toward equality or
# hashes, or every compare produces phantom conflicts and drift.
_IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _is_junk(path: Path) -> bool:
    return path.name in _IGNORED_NAMES or path.name.startswith("._")


def skill_files(path: Path) -> Dict[str, Path]:
    """Content files in a skill dir, relative path -> absolute path.
    Single source of truth for what counts as skill content; dir_hash and
    dirs_equal must agree or drift detection disagrees with itself."""
    return {
        p.relative_to(path).as_posix(): p
        for p in path.rglob("*")
        if p.is_file() and not _is_junk(p)
    }


def dir_hash(path: Path) -> str:
    """Content fingerprint of a directory: sha256 over sorted
    (relative path, file bytes) pairs. Stable across mtime/mode noise."""
    h = hashlib.sha256()
    for rel, p in sorted(skill_files(path).items()):
        h.update(rel.encode() + b"\0")
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
            # A corrupt or hand-edited section must not crash later lookups:
            # anything that is not a dict starts over empty.
            for key in ("skills", "providers", "conflicts"):
                if not isinstance(loaded.get(key), dict):
                    loaded[key] = {}
            self.data = loaded

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    # ---- unified-store section ----

    def record_source(
        self, name: str, content_hash: str, origin: Optional[str] = None, when: Optional[str] = None
    ) -> bool:
        """Register the current unified-store hash for a skill. Sets
        createdAt on first sight; bumps updatedAt whenever the hash moves.
        'when' seeds the timestamps on first record (e.g. content mtime for
        pre-existing skills); later changes always stamp the time observed.
        Returns True when the record changed."""
        changed = False
        entry = self.data["skills"].get(name)
        if not isinstance(entry, dict):
            # Missing or corrupt (hand-edited) entry: start it over.
            entry = {"createdAt": when or _now()}
            self.data["skills"][name] = entry
            changed = True
        if entry.get("hash") != content_hash:
            entry["hash"] = content_hash
            entry["updatedAt"] = when or _now()
            changed = True
        if origin and entry.get("origin") != origin:
            entry["origin"] = origin
            changed = True
        return changed

    def source_hash(self, name: str) -> Optional[str]:
        entry = self.data["skills"].get(name)
        return entry.get("hash") if isinstance(entry, dict) else None

    def reconcile_sources(self, skills_dir: Path) -> bool:
        """Refresh 'skills' entries for every skill dir on disk. New entries
        are timestamped from the newest file mtime (a real "last updated"
        for pre-existing skills, not just first time ai-config noticed).
        Skills installed by the npm 'skills' CLI (recorded in the sibling
        .skill-lock.json) get origin stamped as 'github:<source>' so
        repo-sourced skills stay distinguishable from authored ones.
        Returns True when the lock changed."""
        npm_lock = skills_dir.parent / NPM_LOCK_NAME
        npm_origins = self._npm_lock_origins(npm_lock)
        changed = False
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            d = skill_md.parent
            # Dot-dirs are tool internals (staging, backups), never skills.
            if d.name.startswith("."):
                continue
            latest = max((p.stat().st_mtime for p in skill_files(d).values()), default=None)
            when = (
                datetime.fromtimestamp(latest, timezone.utc).isoformat(timespec="seconds")
                if latest
                else None
            )
            changed |= self.record_source(
                d.name, dir_hash(d), origin=npm_origins.get(d.name), when=when
            )
            if npm_lock.is_file() and d.name not in npm_origins:
                entry = self.data["skills"].get(d.name)
                if isinstance(entry, dict) and str(entry.get("origin", "")).startswith("github:"):
                    del entry["origin"]
                    changed = True
        # Drop entries for skills whose dirs vanished (renames, removals) -
        # the lock records what is on disk, not what once was.
        for name in list(self.data["skills"]):
            if not (skills_dir / name / "SKILL.md").is_file():
                del self.data["skills"][name]
                changed = True
        return changed

    @staticmethod
    def _npm_lock_origins(path: Path) -> Dict[str, str]:
        """Map of skill name -> 'github:<source>' from a sibling npm
        skills-CLI lockfile, if one exists. The npm CLI is optional - this
        only reads a lockfile it happens to have written, for provenance."""
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        origins = {}
        for name, entry in (data.get("skills") or {}).items():
            if isinstance(entry, dict) and entry.get("sourceType") == "github":
                origins[name] = f"github:{entry.get('source', '')}".rstrip(":")
        return origins

    # ---- provider section ----

    def record_sync(self, provider: str, name: str, content_hash: str) -> None:
        """Record that content_hash was pushed to provider for skill name."""
        prov = self.data["providers"].get(provider)
        if not isinstance(prov, dict):
            prov = {}
            self.data["providers"][provider] = prov
        skills = prov.get("skills")
        if not isinstance(skills, dict):
            skills = {}
            prov["skills"] = skills
        skills[name] = {"hash": content_hash, "syncedAt": _now()}

    def provider_hash(self, provider: str, name: str) -> Optional[str]:
        """Hash last pushed to provider, or None if never recorded."""
        prov = self.data["providers"].get(provider)
        if not isinstance(prov, dict):
            return None
        skills = prov.get("skills")
        if not isinstance(skills, dict):
            return None
        entry = skills.get(name)
        return entry.get("hash") if isinstance(entry, dict) else None

    def forget_sync(self, provider: str, name: str) -> None:
        """Drop a provider receipt, e.g. after --prune removes the copy."""
        prov = self.data["providers"].get(provider)
        if isinstance(prov, dict):
            skills = prov.get("skills")
            if isinstance(skills, dict):
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
        entries = self.data["conflicts"].setdefault(name, [])
        if not isinstance(entries, list):
            entries = []
            self.data["conflicts"][name] = entries
        entries.append(entry)

    def prune_conflicts(self) -> int:
        """Drop conflict entries whose quarantinedTo path no longer exists -
        the parked copy is gone, so the conflict is resolved by deletion.
        Entries with no recorded path (skipped) stay until handled another
        way. Returns entries removed."""
        removed = 0
        for name in list(self.data["conflicts"]):
            entries = self.data["conflicts"][name]
            if not isinstance(entries, list):
                # Corrupt entry (hand-edited): drop it rather than crash.
                del self.data["conflicts"][name]
                continue
            kept = [
                e
                for e in entries
                if isinstance(e, dict)
                and (not e.get("quarantinedTo") or Path(e["quarantinedTo"]).exists())
            ]
            removed += len(entries) - len(kept)
            if kept:
                self.data["conflicts"][name] = kept
            else:
                del self.data["conflicts"][name]
        return removed

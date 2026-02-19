"""
schema_cache.py — Load, save, and index Salesforce schema snapshots.

Each snapshot is a directory of JSON files (one per SObject) plus an _index.json
and an _meta.json.  This module provides the read/write API consumed by core/
modules and the sync script.  No MCP, no ML — pure data I/O.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Public API ────────────────────────────────────────────────────────────────

def load_object(cache_dir: str | Path, object_name: str) -> dict[str, Any] | None:
    """Load a single SObject JSON from the cache, with case-insensitive fallback.

    Args:
        cache_dir: Path to the schema cache directory.
        object_name: Salesforce API name (e.g. ``Account``).

    Returns:
        Parsed object dict, or ``None`` if not found.
    """
    cache_dir = Path(cache_dir)
    # Exact match first
    path = cache_dir / f"{object_name}.json"
    if path.exists():
        return json.loads(path.read_text())

    # Case-insensitive fallback
    for f in cache_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        if f.stem.lower() == object_name.lower():
            return json.loads(f.read_text())

    return None


def load_index(cache_dir: str | Path) -> list[dict[str, Any]]:
    """Load the ``_index.json`` summary list.

    Returns:
        List of dicts with keys ``name``, ``label``, ``custom``, ``field_count``.
        Empty list if the index file does not exist.
    """
    index_path = Path(cache_dir) / "_index.json"
    if not index_path.exists():
        return []
    return json.loads(index_path.read_text())


def load_snapshot(cache_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load every SObject file in *cache_dir* into a single dict.

    Returns:
        ``{api_name: object_dict}`` for all non-underscore JSON files.
    """
    cache_dir = Path(cache_dir)
    snapshot: dict[str, dict[str, Any]] = {}
    if not cache_dir.exists():
        return snapshot
    for f in sorted(cache_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        obj = json.loads(f.read_text())
        snapshot[obj["name"]] = obj
    return snapshot


def load_meta(cache_dir: str | Path) -> dict[str, Any] | None:
    """Load ``_meta.json`` (sync timestamp, org info).

    Returns:
        Parsed dict or ``None`` if not present.
    """
    meta_path = Path(cache_dir) / "_meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def save_object(cache_dir: str | Path, obj: dict[str, Any]) -> Path:
    """Persist a single SObject dict as ``<api_name>.json``.

    Args:
        cache_dir: Target directory (created if missing).
        obj: SObject dict — must contain a ``name`` key.

    Returns:
        Path to the written file.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{obj['name']}.json"
    path.write_text(json.dumps(obj, indent=2))
    return path


def save_index(cache_dir: str | Path, index: list[dict[str, Any]]) -> Path:
    """Write the ``_index.json`` summary file."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "_index.json"
    path.write_text(json.dumps(index, indent=2))
    return path


def save_meta(cache_dir: str | Path, meta: dict[str, Any]) -> Path:
    """Write the ``_meta.json`` metadata file."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "_meta.json"
    path.write_text(json.dumps(meta, indent=2))
    return path


def build_index(cache_dir: str | Path) -> list[dict[str, Any]]:
    """Rebuild ``_index.json`` from the individual object files on disk.

    Returns:
        The newly built index list (also written to disk).
    """
    snapshot = load_snapshot(cache_dir)
    index = [
        {
            "name": obj["name"],
            "label": obj.get("label", obj["name"]),
            "custom": obj.get("custom", False),
            "field_count": len(obj.get("fields", [])),
        }
        for obj in sorted(snapshot.values(), key=lambda o: o["name"])
    ]
    save_index(cache_dir, index)
    return index


# ── Multi-org registry ────────────────────────────────────────────────────────

def load_orgs(cache_root: str | Path) -> dict[str, dict[str, Any]]:
    """Load the ``_orgs.json`` registry mapping org aliases to cache metadata.

    Returns:
        ``{alias: {cache_dir, instance_url, username, ...}}``.
        Empty dict if no registry exists.
    """
    orgs_path = Path(cache_root) / "_orgs.json"
    if not orgs_path.exists():
        return {}
    return json.loads(orgs_path.read_text())


def save_orgs(cache_root: str | Path, orgs: dict[str, dict[str, Any]]) -> Path:
    """Write the ``_orgs.json`` registry file."""
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    path = cache_root / "_orgs.json"
    path.write_text(json.dumps(orgs, indent=2))
    return path


def resolve_org_cache_dir(cache_root: str | Path, org_alias: str) -> Path:
    """Resolve an org alias to its cache subdirectory.

    Looks up *org_alias* in ``_orgs.json`` first.  If not found, falls back
    to the convention ``<cache_root>/<org_alias>/``.
    """
    cache_root = Path(cache_root)
    orgs = load_orgs(cache_root)
    if org_alias in orgs:
        return Path(orgs[org_alias]["cache_dir"])
    return cache_root / org_alias


def is_stale(cache_dir: str | Path, hours: int = 24) -> bool:
    """Check whether the cache is older than *hours* based on ``_meta.json``.

    Returns:
        ``True`` if meta is missing or the ``synced_at`` timestamp is older
        than *hours* ago.
    """
    meta = load_meta(cache_dir)
    if meta is None:
        return True
    synced_at = meta.get("synced_at")
    if synced_at is None:
        return True
    try:
        synced_dt = datetime.fromisoformat(synced_at)
    except (TypeError, ValueError):
        return True
    now = datetime.now(timezone.utc)
    if synced_dt.tzinfo is None:
        synced_dt = synced_dt.replace(tzinfo=timezone.utc)
    age_hours = (now - synced_dt).total_seconds() / 3600
    return age_hours > hours

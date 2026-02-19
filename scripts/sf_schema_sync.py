#!/usr/bin/env python3
"""
sf_schema_sync.py — Sync Salesforce org schema to a local cache.

Uses the Salesforce REST API (describe) to download all SObject metadata
and persist one JSON file per object, plus an _index.json and _meta.json.

Usage:
    # Using sf CLI org alias (recommended)
    python scripts/sf_schema_sync.py --org sfsdemo
    python scripts/sf_schema_sync.py --org sfsdemo --objects Account --objects Contact

    # Using environment variables (legacy)
    python scripts/sf_schema_sync.py --cache-dir ./schema-cache
    python scripts/sf_schema_sync.py --cache-dir ./schema-cache --objects Account
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import sf_api
from src.data.schema_cache import build_index, save_meta, save_object, load_orgs, save_orgs


def _get_session_for_org(org_alias: str | None = None) -> tuple[str, str, dict[str, str]]:
    """Return (instance_url, access_token, org_info) for the given org.

    Resolution order:
      1. If org_alias is provided, use ``sf org display -o <alias> --json``
      2. Fall back to SF_INSTANCE_URL / SF_ACCESS_TOKEN from env / .env

    Returns:
        Tuple of (instance_url, access_token, org_info_dict).
    """
    if org_alias:
        try:
            instance_url, access_token = sf_api.get_session(org_alias)
        except RuntimeError as e:
            click.echo(f"ERROR: {e}", err=True)
            raise SystemExit(1)
        org_info = {
            "alias": org_alias,
            "username": "",
            "instance_url": instance_url,
        }
        return instance_url, access_token, org_info
    return _get_session_from_env()


def _get_session_from_env() -> tuple[str, str, dict[str, str]]:
    """Legacy: get credentials from environment variables / .env file."""
    load_dotenv()
    instance_url = os.environ.get("SF_INSTANCE_URL", "").rstrip("/")
    access_token = os.environ.get("SF_ACCESS_TOKEN", "")
    if not instance_url or not access_token:
        click.echo(
            "ERROR: Set SF_INSTANCE_URL and SF_ACCESS_TOKEN, or use --org <alias>.",
            err=True,
        )
        raise SystemExit(1)
    return instance_url, access_token, {"alias": "", "username": "", "instance_url": instance_url}


@click.command()
@click.option(
    "--org", "org_alias", default=None,
    help="Salesforce CLI org alias (e.g. sfsdemo). Gets credentials via 'sf org display'.",
)
@click.option(
    "--cache-dir", default=None,
    help="Directory to write cached schema files. Auto-resolved from --org if omitted.",
)
@click.option(
    "--objects",
    multiple=True,
    help="Specific object API names to sync. Omit to sync all queryable objects.",
)
def sync(org_alias: str | None, cache_dir: str | None, objects: tuple[str, ...]) -> None:
    """Sync Salesforce schema to a local JSON cache."""
    instance_url, token, org_info = _get_session_for_org(org_alias)

    # Resolve cache directory
    cache_root = os.environ.get("SF_SCHEMA_CACHE", "./schema-cache")
    if cache_dir:
        cache_path = Path(cache_dir)
    elif org_alias:
        cache_path = Path(cache_root) / org_alias
    else:
        cache_path = Path(cache_root)

    if objects:
        api_names = list(objects)
        click.echo(f"Syncing {len(api_names)} specified object(s)...")
    else:
        click.echo("Fetching SObject list...")
        sobjects = sf_api.list_sobjects(instance_url, token)
        api_names = [
            s["name"] for s in sobjects
            if s.get("queryable") and not s["name"].endswith("__History")
        ]
        click.echo(f"Found {len(api_names)} queryable objects.")

    synced = 0
    errors = []
    for i, name in enumerate(api_names, 1):
        try:
            click.echo(f"  [{i}/{len(api_names)}] {name}...", nl=False)
            raw = sf_api.describe_object(instance_url, token, name)
            obj = sf_api.normalise(raw)
            save_object(cache_path, obj)
            synced += 1
            click.echo(" OK")
        except Exception as e:
            errors.append((name, str(e)))
            click.echo(f" ERROR ({e})")

    # Rebuild index
    click.echo("Rebuilding index...")
    build_index(cache_path)

    # Write meta
    save_meta(cache_path, {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "instance_url": instance_url,
        "objects_synced": synced,
        "objects_failed": len(errors),
        "api_version": "v60.0",
    })

    # Update org registry if using --org
    if org_alias:
        orgs = load_orgs(cache_root)
        orgs[org_alias] = {
            "cache_dir": str(cache_path.resolve()),
            "instance_url": instance_url,
            "username": org_info.get("username", ""),
            "alias": org_alias,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        save_orgs(cache_root, orgs)
        click.echo(f"Org '{org_alias}' registered in {cache_root}/_orgs.json")

    click.echo(f"\nDone. Synced: {synced}, Failed: {len(errors)}")
    if errors:
        click.echo("Failed objects:")
        for name, err in errors:
            click.echo(f"  {name}: {err}")


if __name__ == "__main__":
    sync()

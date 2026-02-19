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

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import requests
from dotenv import load_dotenv

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
        return _get_session_from_sf_cli(org_alias)
    return _get_session_from_env()


def _get_session_from_sf_cli(org_alias: str) -> tuple[str, str, dict[str, str]]:
    """Get credentials from the Salesforce CLI."""
    try:
        result = subprocess.run(
            ["sf", "org", "display", "-o", org_alias, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            click.echo(f"ERROR: sf org display failed for '{org_alias}'.", err=True)
            try:
                err_data = json.loads(result.stdout)
                click.echo(f"  {err_data.get('message', result.stderr)}", err=True)
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {result.stderr}", err=True)
            raise SystemExit(1)
        data = json.loads(result.stdout)["result"]
        instance_url = data["instanceUrl"].rstrip("/")
        access_token = data["accessToken"]
        org_info = {
            "alias": org_alias,
            "username": data.get("username", ""),
            "instance_url": instance_url,
        }
        return instance_url, access_token, org_info
    except FileNotFoundError:
        click.echo(
            "ERROR: 'sf' CLI not found. Install it from "
            "https://developer.salesforce.com/tools/salesforcecli or use .env.",
            err=True,
        )
        raise SystemExit(1)


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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _list_sobjects(instance_url: str, token: str) -> list[dict]:
    """Fetch the global describe to get the list of all SObjects."""
    url = f"{instance_url}/services/data/v60.0/sobjects"
    resp = requests.get(url, headers=_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()["sobjects"]


def _describe_object(instance_url: str, token: str, api_name: str) -> dict:
    """Fetch full describe for a single SObject."""
    url = f"{instance_url}/services/data/v60.0/sobjects/{api_name}/describe"
    resp = requests.get(url, headers=_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _normalise(raw: dict) -> dict:
    """Transform raw Salesforce describe into our cache format."""
    fields = []
    for f in raw.get("fields", []):
        field = {
            "name": f["name"],
            "label": f["label"],
            "type": f["type"].lower(),
            "required": not f.get("nillable", True) and not f.get("defaultedOnCreate", False),
            "external_id": f.get("externalId", False),
            "reference_to": [r for r in (f.get("referenceTo") or [])],
            "picklist_values": [p["value"] for p in (f.get("picklistValues") or []) if p.get("active")],
        }
        fields.append(field)

    child_rels = []
    for r in raw.get("childRelationships", []):
        if r.get("childSObject") and r.get("field"):
            child_rels.append({
                "child_sobject": r["childSObject"],
                "field": r["field"],
                "relationship_name": r.get("relationshipName") or "",
            })

    return {
        "name": raw["name"],
        "label": raw.get("label", raw["name"]),
        "label_plural": raw.get("labelPlural", ""),
        "custom": raw.get("custom", False),
        "fields": fields,
        "child_relationships": child_rels,
    }


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
        sobjects = _list_sobjects(instance_url, token)
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
            raw = _describe_object(instance_url, token, name)
            obj = _normalise(raw)
            save_object(cache_path, obj)
            synced += 1
            click.echo(" OK")
        except requests.HTTPError as e:
            errors.append((name, str(e)))
            click.echo(f" FAILED ({e})")
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

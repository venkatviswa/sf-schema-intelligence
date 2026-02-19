"""
sf_api.py — Salesforce REST API helpers shared by the sync script and MCP server.

Handles credential retrieval via the ``sf`` CLI and object describe calls.
No MCP, no Click — pure API I/O.
"""
from __future__ import annotations

import json
import subprocess

import requests


def get_session(org_alias: str) -> tuple[str, str]:
    """Get ``(instance_url, access_token)`` from the Salesforce CLI.

    Runs ``sf org display -o <alias> --json`` and parses the result.

    Raises:
        RuntimeError: If the sf CLI is not installed or the command fails.
    """
    try:
        result = subprocess.run(
            ["sf", "org", "display", "-o", org_alias, "--json"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "'sf' CLI not found. Install from "
            "https://developer.salesforce.com/tools/salesforcecli"
        )

    if result.returncode != 0:
        try:
            err_data = json.loads(result.stdout)
            msg = err_data.get("message", result.stderr)
        except (json.JSONDecodeError, KeyError):
            msg = result.stderr
        raise RuntimeError(f"sf org display failed for '{org_alias}': {msg}")

    data = json.loads(result.stdout)["result"]
    instance_url = data["instanceUrl"].rstrip("/")
    access_token = data["accessToken"]
    return instance_url, access_token


def describe_object(instance_url: str, token: str, api_name: str) -> dict:
    """Fetch full describe metadata for a single SObject.

    Returns:
        Raw Salesforce describe dict.

    Raises:
        requests.HTTPError: If the API call fails.
    """
    url = f"{instance_url}/services/data/v60.0/sobjects/{api_name}/describe"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def list_sobjects(instance_url: str, token: str) -> list[dict]:
    """Fetch the global describe to get the list of all SObjects."""
    url = f"{instance_url}/services/data/v60.0/sobjects"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["sobjects"]


def normalise(raw: dict) -> dict:
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

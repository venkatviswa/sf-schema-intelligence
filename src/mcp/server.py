"""
server.py — FastMCP server exposing Salesforce schema tools.

Thin wrappers only.  Every @mcp.tool is <= 10 lines.
All business logic lives in core/ and data/.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastmcp import FastMCP

from src.core import diff, er_diagram, graph
from src.data import schema_cache, sf_api

CACHE_ROOT = os.environ.get("SF_SCHEMA_CACHE", "./schema-cache")

# ── Multi-org state ──────────────────────────────────────────────────────────

def _init_active_cache_dir() -> str:
    """Detect legacy vs multi-org layout and pick the initial cache dir."""
    root = Path(CACHE_ROOT)
    orgs = schema_cache.load_orgs(CACHE_ROOT)
    if orgs:
        # Multi-org: auto-select if exactly one org registered
        if len(orgs) == 1:
            return list(orgs.values())[0]["cache_dir"]
        return CACHE_ROOT  # multiple orgs — user must call switch_org
    # Legacy: root dir contains object files directly
    return CACHE_ROOT

_active_cache_dir: str = _init_active_cache_dir()


def _get_cache_dir() -> str:
    """Return the currently active cache directory."""
    return _active_cache_dir


def _resolve_cache_dir(value: str) -> str:
    """Resolve a value that may be an org alias or a raw directory path."""
    orgs = schema_cache.load_orgs(CACHE_ROOT)
    if value in orgs:
        return orgs[value]["cache_dir"]
    return value


mcp = FastMCP(
    name="Salesforce Schema Intelligence",
    instructions=(
        "You have access to Salesforce schema caches for one or more orgs. "
        "Use list_orgs to see available orgs. Use switch_org to change the active org. "
        "ALWAYS call get_object_schema before writing Apex, SOQL, or Flow definitions. "
        "ALWAYS call generate_er_diagram (not freehand Mermaid) for ER diagrams. "
        "Never assume field names or relationships — verify first. "
        "Use refresh_object to re-fetch a single object after schema changes in Salesforce."
    ),
)


@mcp.tool
def list_orgs() -> str:
    """List all synced Salesforce orgs and show which is currently active."""
    orgs = schema_cache.load_orgs(CACHE_ROOT)
    if not orgs:
        meta = schema_cache.load_meta(CACHE_ROOT)
        if meta:
            return f"Single org (legacy mode): {meta.get('instance_url', 'unknown')}\nActive: {CACHE_ROOT}"
        return "No orgs synced. Run: python scripts/sf_schema_sync.py --org <alias>"
    lines = [f"Synced orgs ({len(orgs)}):"]
    for alias, info in sorted(orgs.items()):
        active = " (ACTIVE)" if info["cache_dir"] == _active_cache_dir else ""
        lines.append(f"  {alias}: {info['instance_url']}{active}")
    return "\n".join(lines)


@mcp.tool
def switch_org(org: str) -> str:
    """Switch the active org for all subsequent schema queries."""
    global _active_cache_dir
    orgs = schema_cache.load_orgs(CACHE_ROOT)
    if org not in orgs:
        available = ", ".join(sorted(orgs.keys())) if orgs else "none"
        return f"Org '{org}' not found. Available: {available}"
    _active_cache_dir = orgs[org]["cache_dir"]
    meta = schema_cache.load_meta(_active_cache_dir)
    synced = meta.get("synced_at", "unknown") if meta else "unknown"
    return f"Switched to '{org}' ({orgs[org]['instance_url']}). Last synced: {synced}"


@mcp.tool
def refresh_object(object_name: str) -> str:
    """Re-fetch a single object's schema from Salesforce and update the cache.

    Useful when you've just added or modified fields and need fresh metadata
    without running a full sync.
    """
    # Find the active org alias from the registry
    orgs = schema_cache.load_orgs(CACHE_ROOT)
    cache_dir = _get_cache_dir()
    org_alias = None
    for alias, info in orgs.items():
        if info["cache_dir"] == cache_dir:
            org_alias = alias
            break
    if not org_alias:
        return (
            "Cannot refresh: no active org with sf CLI credentials. "
            "Use 'python scripts/sf_schema_sync.py --org <alias>' from the terminal."
        )
    try:
        instance_url, token = sf_api.get_session(org_alias)
        raw = sf_api.describe_object(instance_url, token, object_name)
    except RuntimeError as e:
        return f"Refresh failed: {e}"
    except Exception as e:
        return f"Refresh failed (API error): {e}"

    obj = sf_api.normalise(raw)
    schema_cache.save_object(cache_dir, obj)
    schema_cache.build_index(cache_dir)
    field_count = len(obj.get("fields", []))
    return (
        f"Refreshed '{object_name}' from {org_alias} ({instance_url}). "
        f"{field_count} fields, {len(obj.get('child_relationships', []))} child relationships."
    )


@mcp.tool
def get_object_schema(object_name: str, key_fields_only: bool = False) -> str:
    """Return full field definitions and relationships for a Salesforce object."""
    obj = schema_cache.load_object(_get_cache_dir(), object_name)
    if not obj:
        return f"Object '{object_name}' not found in cache."
    if key_fields_only:
        return _format_object_key_fields(obj)
    return _format_object(obj)


@mcp.tool
def search_objects(keyword: str, custom_only: bool = False) -> str:
    """Search for Salesforce objects by keyword in API name or label."""
    index = schema_cache.load_index(_get_cache_dir())
    kw = keyword.lower()
    matches = [
        o for o in index
        if (kw in o["name"].lower() or kw in o["label"].lower())
        and (not custom_only or o["custom"])
    ]
    if not matches:
        return f"No objects matching '{keyword}'."
    lines = [f"Found {len(matches)} object(s):"]
    for o in matches:
        lines.append(f"  {o['name']} — {o['label']} ({o['field_count']} fields)")
    return "\n".join(lines)


@mcp.tool
def list_all_objects(custom_only: bool = False) -> str:
    """List all Salesforce objects in the schema cache."""
    index = schema_cache.load_index(_get_cache_dir())
    objs = [o for o in index if not custom_only or o["custom"]]
    lines = [f"{len(objs)} objects in cache:"]
    for o in objs:
        lines.append(f"  {o['name']} ({o['label']}) — {o['field_count']} fields")
    return "\n".join(lines)


@mcp.tool
def get_object_relationships(object_name: str) -> str:
    """Return relationship fields (lookup, master-detail, child) for an object."""
    obj = schema_cache.load_object(_get_cache_dir(), object_name)
    if not obj:
        return f"Object '{object_name}' not found."
    return _format_relationships(obj)


@mcp.tool
def generate_er_diagram_tool(
    root_objects: list[str],
    depth: int = 1,
    direction: str = "both",
    include_fields: bool = True,
    field_filter: str = "relationships",
    format: str = "mermaid",
) -> str:
    """Generate a deterministic ER diagram from the real schema cache."""
    snapshot = schema_cache.load_snapshot(_get_cache_dir())
    g = graph.build_graph(snapshot)
    objects_map, edges = graph.collect_subgraph(g, root_objects, depth, direction)
    if not objects_map:
        return "No objects found. Check names with search_objects."
    diagram = er_diagram.generate_er_diagram(
        objects_map, edges, include_fields, field_filter, max_fields=20, format=format,
    )
    return f"Objects: {len(objects_map)} | Edges: {len(edges)}\n\n```{format}\n{diagram}\n```"


@mcp.tool
def generate_hierarchy_diagram_tool(
    object_name: str,
    max_levels: int = 3,
    format: str = "mermaid",
) -> str:
    """Generate a hierarchy diagram for a self-referencing Salesforce object."""
    snapshot = schema_cache.load_snapshot(_get_cache_dir())
    return er_diagram.generate_hierarchy_diagram(object_name, snapshot, max_levels, format)


@mcp.tool
def compare_schemas(cache_dir_a: str, cache_dir_b: str) -> str:
    """Compare two schema snapshots and produce a structured diff report.

    Arguments can be org aliases (e.g. 'sfsdemo') or directory paths.
    """
    dir_a = _resolve_cache_dir(cache_dir_a)
    dir_b = _resolve_cache_dir(cache_dir_b)
    snap_a = schema_cache.load_snapshot(dir_a)
    snap_b = schema_cache.load_snapshot(dir_b)
    result = diff.compare_snapshots(snap_a, snap_b)
    return result.as_text_report()


@mcp.tool
def get_schema_meta(cache_dir: str | None = None) -> str:
    """Return metadata about the schema cache (last sync, org info).

    Accepts an org alias or directory path. Defaults to the active org.
    """
    if cache_dir:
        target = _resolve_cache_dir(cache_dir)
    else:
        target = _get_cache_dir()
    meta = schema_cache.load_meta(target)
    if not meta:
        return "No schema cache found. Run sf_schema_sync.py first."
    import json
    return json.dumps(meta, indent=2)


# ── Helpers (not tools) ──────────────────────────────────────────────────────

def _format_object_key_fields(obj: dict) -> str:
    """Format an object showing only key fields (Id, external IDs, relationships, required)."""
    selected, truncated, total = er_diagram.select_fields(obj, field_filter="required", max_fields=20)
    lines = [
        f"Object: {obj['name']} ({obj['label']})",
        f"Custom: {obj['custom']}",
        f"\nKey Fields ({len(selected)} of {total} total):",
    ]
    for f in selected:
        ref = f" -> {', '.join(f['reference_to'])}" if f.get("reference_to") else ""
        req = " [REQUIRED]" if f.get("required") else ""
        lines.append(f"  {f['name']} ({f['type']}){ref}{req}")
    if truncated:
        lines.append(f"\n  ... {total - len(selected)} more fields omitted. Use key_fields_only=False for full schema.")
    if obj.get("child_relationships"):
        lines.append(f"\nChild Relationships ({len(obj['child_relationships'])}):")
        for r in obj["child_relationships"]:
            lines.append(f"  <- {r['child_sobject']}.{r['field']} (rel: {r['relationship_name']})")
    return "\n".join(lines)


def _format_object(obj: dict) -> str:
    lines = [
        f"Object: {obj['name']} ({obj['label']})",
        f"Custom: {obj['custom']}",
        f"\nFields ({len(obj['fields'])}):",
    ]
    for f in obj["fields"]:
        ref = f" -> {', '.join(f['reference_to'])}" if f.get("reference_to") else ""
        req = " [REQUIRED]" if f.get("required") else ""
        lines.append(f"  {f['name']} ({f['type']}){ref}{req}")
    if obj.get("child_relationships"):
        lines.append(f"\nChild Relationships ({len(obj['child_relationships'])}):")
        for r in obj["child_relationships"]:
            lines.append(f"  <- {r['child_sobject']}.{r['field']} (rel: {r['relationship_name']})")
    return "\n".join(lines)


def _format_relationships(obj: dict) -> str:
    rel_fields = [
        f for f in obj["fields"]
        if f["type"] in ("reference", "masterdetail") and f.get("reference_to")
    ]
    lines = [f"Relationships for {obj['name']}:", "", "Outbound:"]
    if rel_fields:
        for f in rel_fields:
            lines.append(f"  {f['name']} ({f['type']}) -> {', '.join(f['reference_to'])}")
    else:
        lines.append("  None")
    lines.append("\nInbound:")
    if obj.get("child_relationships"):
        for r in obj["child_relationships"]:
            lines.append(f"  {r['child_sobject']}.{r['field']} (rel: {r['relationship_name']})")
    else:
        lines.append("  None")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()

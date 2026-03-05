"""
workbook.py — Generate a Markdown data integrity workbook from cached schema.

Pure rendering — no I/O, no MCP.  Accepts loaded data structures and returns
Markdown text.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def generate_workbook(
    snapshot: dict[str, dict[str, Any]],
    index: list[dict[str, Any]],
    meta: dict[str, Any] | None,
    objects: list[str] | None = None,
    include_picklists: bool = True,
) -> str:
    """Generate a complete Markdown data integrity workbook.

    Args:
        snapshot: ``{api_name: object_dict}`` from ``schema_cache.load_snapshot()``.
        index: List of dicts from ``schema_cache.load_index()``.
        meta: Dict from ``schema_cache.load_meta()``, or ``None``.
        objects: If provided, restrict to these object API names. ``None`` = all.
        include_picklists: Whether to include picklist values in field dictionary.

    Returns:
        Complete Markdown document as a string.
    """
    if objects:
        obj_set = set(objects)
        snapshot = {k: v for k, v in snapshot.items() if k in obj_set}
        index = [o for o in index if o["name"] in obj_set]

    sections = [
        _render_executive_summary(snapshot, index, meta),
        _render_object_inventory(index, snapshot),
        _render_field_dictionary(snapshot, include_picklists),
        _render_relationship_map(snapshot),
        _render_aggregate_metrics(snapshot, index),
    ]
    return "\n\n---\n\n".join(sections) + "\n"


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_executive_summary(
    snapshot: dict[str, dict[str, Any]],
    index: list[dict[str, Any]],
    meta: dict[str, Any] | None,
) -> str:
    lines = ["# Data Integrity Workbook", ""]

    if meta:
        lines.append(f"**Org:** {meta.get('instance_url', 'Unknown')}")
        lines.append(f"**Synced:** {meta.get('synced_at', 'Unknown')}")
        lines.append(f"**API Version:** {meta.get('api_version', 'Unknown')}")
        lines.append("")

    total_objects = len(index)
    custom_count = sum(1 for o in index if o.get("custom"))
    standard_count = total_objects - custom_count
    total_fields = sum(o.get("field_count", 0) for o in index)

    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Objects | {total_objects} |")
    lines.append(f"| Standard Objects | {standard_count} |")
    lines.append(f"| Custom Objects | {custom_count} |")
    lines.append(f"| Total Fields | {total_fields} |")

    return "\n".join(lines)


def _render_object_inventory(
    index: list[dict[str, Any]],
    snapshot: dict[str, dict[str, Any]],
) -> str:
    lines = ["## Object Inventory", ""]
    lines.append("| Object API Name | Label | Custom | Fields | Relationships |")
    lines.append("|-----------------|-------|--------|--------|---------------|")

    for o in sorted(index, key=lambda x: x["name"]):
        name = o["name"]
        label = o.get("label", name)
        custom = "Yes" if o.get("custom") else "No"
        field_count = o.get("field_count", 0)

        # Count relationships from the snapshot
        obj = snapshot.get(name, {})
        outbound = sum(
            1 for f in obj.get("fields", [])
            if f["type"] in ("reference", "masterdetail") and f.get("reference_to")
        )
        inbound = len(obj.get("child_relationships", []))
        rel_count = outbound + inbound

        lines.append(f"| {name} | {label} | {custom} | {field_count} | {rel_count} |")

    return "\n".join(lines)


def _render_field_dictionary(
    snapshot: dict[str, dict[str, Any]],
    include_picklists: bool = True,
) -> str:
    lines = ["## Field Dictionary", ""]

    for obj_name in sorted(snapshot):
        obj = snapshot[obj_name]
        label = obj.get("label", obj_name)
        lines.append(f"### {obj_name} ({label})")
        lines.append("")

        if include_picklists:
            lines.append("| Field | Label | Type | Required | External ID | References | Picklist Values |")
            lines.append("|-------|-------|------|----------|-------------|------------|-----------------|")
        else:
            lines.append("| Field | Label | Type | Required | External ID | References |")
            lines.append("|-------|-------|------|----------|-------------|------------|")

        for f in obj.get("fields", []):
            fname = f["name"]
            flabel = f.get("label", fname)
            ftype = f.get("type", "")
            required = "Yes" if f.get("required") else "No"
            ext_id = "Yes" if f.get("external_id") else "No"
            refs = ", ".join(f.get("reference_to", []))

            if include_picklists:
                pvals = f.get("picklist_values", [])
                if len(pvals) > 10:
                    picklist_str = ", ".join(pvals[:10]) + f" (+{len(pvals) - 10} more)"
                else:
                    picklist_str = ", ".join(pvals)
                lines.append(f"| {fname} | {flabel} | {ftype} | {required} | {ext_id} | {refs} | {picklist_str} |")
            else:
                lines.append(f"| {fname} | {flabel} | {ftype} | {required} | {ext_id} | {refs} |")

        lines.append("")

    return "\n".join(lines)


def _render_relationship_map(
    snapshot: dict[str, dict[str, Any]],
) -> str:
    lines = ["## Relationship Map", ""]
    lines.append("| Source Object | Field | Type | Target Object |")
    lines.append("|--------------|-------|------|---------------|")

    for obj_name in sorted(snapshot):
        obj = snapshot[obj_name]
        for f in obj.get("fields", []):
            if f["type"] in ("reference", "masterdetail") and f.get("reference_to"):
                for target in f["reference_to"]:
                    lines.append(f"| {obj_name} | {f['name']} | {f['type']} | {target} |")

    return "\n".join(lines)


def _render_aggregate_metrics(
    snapshot: dict[str, dict[str, Any]],
    index: list[dict[str, Any]],
) -> str:
    lines = ["## Aggregate Metrics", ""]

    # Field type distribution
    type_counter: Counter[str] = Counter()
    for obj in snapshot.values():
        for f in obj.get("fields", []):
            type_counter[f.get("type", "unknown")] += 1

    total_fields = sum(type_counter.values())
    lines.append("### Field Type Distribution")
    lines.append("")
    lines.append("| Field Type | Count | Percentage |")
    lines.append("|------------|-------|------------|")
    for ftype, count in type_counter.most_common():
        pct = (count / total_fields * 100) if total_fields else 0
        lines.append(f"| {ftype} | {count} | {pct:.1f}% |")
    lines.append("")

    # Most connected objects (top 10)
    connections: list[tuple[str, int, int, int]] = []
    for obj_name in snapshot:
        obj = snapshot[obj_name]
        outbound = sum(
            1 for f in obj.get("fields", [])
            if f["type"] in ("reference", "masterdetail") and f.get("reference_to")
        )
        inbound = len(obj.get("child_relationships", []))
        connections.append((obj_name, outbound, inbound, outbound + inbound))

    connections.sort(key=lambda x: x[3], reverse=True)
    lines.append("### Most Connected Objects")
    lines.append("")
    lines.append("| Object | Outbound Refs | Inbound (Child) Rels | Total |")
    lines.append("|--------|---------------|----------------------|-------|")
    for obj_name, out, inb, total in connections[:10]:
        lines.append(f"| {obj_name} | {out} | {inb} | {total} |")
    lines.append("")

    # Objects with most custom fields (top 10)
    custom_fields: list[tuple[str, int, int, float]] = []
    for obj_name in snapshot:
        obj = snapshot[obj_name]
        fields = obj.get("fields", [])
        total_f = len(fields)
        custom_f = sum(1 for f in fields if f["name"].endswith("__c"))
        if custom_f > 0:
            pct = (custom_f / total_f * 100) if total_f else 0
            custom_fields.append((obj_name, custom_f, total_f, pct))

    custom_fields.sort(key=lambda x: x[1], reverse=True)
    if custom_fields:
        lines.append("### Objects With Most Custom Fields")
        lines.append("")
        lines.append("| Object | Custom Fields | Total Fields | % Custom |")
        lines.append("|--------|---------------|--------------|----------|")
        for obj_name, cf, tf, pct in custom_fields[:10]:
            lines.append(f"| {obj_name} | {cf} | {tf} | {pct:.1f}% |")

    return "\n".join(lines)

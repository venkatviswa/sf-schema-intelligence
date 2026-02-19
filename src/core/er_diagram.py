"""
er_diagram.py — Deterministic Mermaid and PlantUML ER diagram renderers.

Two output formats from the same graph data.  No MCP, no ML.
"""
from __future__ import annotations

from typing import Any, Literal


# ── Field selection ───────────────────────────────────────────────────────────

def select_fields(
    obj: dict[str, Any],
    field_filter: Literal["all", "required", "relationships"] = "relationships",
    max_fields: int = 20,
) -> tuple[list[dict[str, Any]], bool, int]:
    """Select which fields to render inside an entity block.

    Priority order:
        1. Id (PK)
        2. External Id fields
        3. Relationship fields (lookup, master-detail)
        4. Required / not-nullable fields
        5. Fill to *max_fields* with remaining if ``field_filter="all"``

    Args:
        obj: SObject dict.
        field_filter: ``"all"`` | ``"required"`` | ``"relationships"``.
        max_fields: Cap on rendered fields.

    Returns:
        ``(selected, truncated, total_count)``
    """
    all_fields = obj.get("fields", [])
    total = len(all_fields)

    # Small-object short-circuit
    if field_filter != "relationships" and total <= max_fields:
        if field_filter == "all":
            return all_fields, False, total
        if field_filter == "required":
            chosen = [
                f for f in all_fields
                if f.get("required")
                or f["type"] in ("reference", "masterdetail")
                or f["name"] == "Id"
            ]
            return chosen, False, total

    seen: set[str] = set()
    selected: list[dict[str, Any]] = []

    def _add(f: dict[str, Any]) -> None:
        if f["name"] not in seen:
            seen.add(f["name"])
            selected.append(f)

    # Tier 1 — PK
    for f in all_fields:
        if f["name"] == "Id":
            _add(f)

    # Tier 2 — External Ids
    for f in all_fields:
        if f.get("external_id"):
            _add(f)

    # Tier 3 — Relationships
    for f in all_fields:
        if f["type"] in ("reference", "masterdetail") and f.get("reference_to"):
            _add(f)

    # Tier 4 — Required
    for f in all_fields:
        if f.get("required") and f["name"] != "Id":
            _add(f)

    # Tier 5 — Fill remaining
    if len(selected) < max_fields and field_filter == "all":
        for f in all_fields:
            if len(selected) >= max_fields:
                break
            if f["type"] not in ("calculated", "encryptedstring", "base64", "address"):
                _add(f)

    truncated = total > len(selected)
    return selected, truncated, total


# ── Mermaid renderer ──────────────────────────────────────────────────────────

def _safe_id(name: str) -> str:
    """Convert an API name to a valid Mermaid/PlantUML identifier."""
    return name.replace("__c", "_c").replace("__", "_").replace("-", "_")


def _mermaid_field_line(f: dict[str, Any]) -> str:
    """Format a single field as a Mermaid entity attribute line."""
    if f["name"] == "Id":
        tag = "PK"
    elif f.get("external_id"):
        tag = "UK"
    elif f["type"] in ("reference", "masterdetail") and f.get("reference_to"):
        tag = "FK"
    else:
        tag = ""

    if f["type"] in ("reference", "masterdetail") and f.get("reference_to"):
        refs = "_".join(f["reference_to"])[:24]
        comment = f"FK_{refs}"
    elif f.get("required") and f["name"] != "Id":
        comment = "NOT_NULL"
    elif f.get("external_id"):
        comment = "EXT_ID"
    else:
        comment = ""

    sf_type = f["type"].upper()[:12]
    fname = f["name"].replace("__c", "_c")
    tag_str = f" {tag}" if tag else ""
    cmt_str = f' "{comment}"' if comment else ""
    return f"        {sf_type} {fname}{tag_str}{cmt_str}"


_MERMAID_REL = {
    "reference": "||--o{",
    "masterdetail": "||--|{",
}


def _render_mermaid(
    objects_map: dict[str, dict[str, Any]],
    edges: list[tuple[str, str, str, str, bool]],
    include_fields: bool,
    field_filter: str,
    max_fields: int,
) -> str:
    lines = ["erDiagram"]
    truncation_notes: list[str] = []

    # Entity blocks
    for obj_name in sorted(objects_map):
        obj = objects_map[obj_name]
        node_id = _safe_id(obj_name)
        if include_fields:
            selected, truncated, total = select_fields(obj, field_filter, max_fields)
            if selected:
                lines.append(f"    {node_id} {{")
                for f in selected:
                    lines.append(_mermaid_field_line(f))
                if truncated:
                    shown = len(selected)
                    omitted = total - shown
                    lines.append(
                        f'        string _note "Key fields only: '
                        f'{shown} shown, {omitted} omitted ({total} total)"'
                    )
                lines.append("    }")
            else:
                lines.append(f"    {node_id} {{ string Id PK }}")
            if truncated:
                label = obj.get("label", obj_name)
                truncation_notes.append(
                    f"    %% {label} ({obj_name}): showing {len(selected)} "
                    f"of {total} fields (PK + ExternalId + Required + FK)"
                )
        else:
            lines.append(f"    {node_id} {{ string Id PK }}")

    lines.append("")

    # Relationships
    seen_pairs: set[tuple[str, str, str]] = set()
    self_refs: list[str] = []

    for from_obj, to_obj, rel_type, field_name, is_self_ref in edges:
        if is_self_ref:
            label = objects_map.get(from_obj, {}).get("label", from_obj)
            self_refs.append(
                f"    %% SELF-REF: {label}.{field_name} -> {label} (hierarchical lookup)"
            )
            continue
        pair = (min(from_obj, to_obj), max(from_obj, to_obj), field_name)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        from_id = _safe_id(from_obj)
        to_id = _safe_id(to_obj)
        symbol = _MERMAID_REL.get(rel_type, "}o--o{")
        lines.append(f'    {from_id} {symbol} {to_id} : "{field_name}"')

    if self_refs:
        lines.append("")
        lines.append("    %% -- Self-Referencing (Hierarchical) Objects --")
        lines.extend(self_refs)

    if truncation_notes:
        lines.append("")
        lines.append("    %% -- Field Truncation Summary --")
        lines.extend(truncation_notes)

    return "\n".join(lines)


# ── PlantUML renderer ────────────────────────────────────────────────────────

def _plantuml_field_line(f: dict[str, Any]) -> str:
    """Format a single field as a PlantUML class attribute line."""
    sf_type = f["type"]
    fname = f["name"]
    markers: list[str] = []
    if f["name"] == "Id":
        markers.append("<<PK>>")
    if f.get("external_id"):
        markers.append("<<UK>>")
    if f["type"] in ("reference", "masterdetail") and f.get("reference_to"):
        markers.append("<<FK>>")
    if f.get("required") and f["name"] != "Id":
        markers.append("{not null}")
    marker_str = " ".join(markers)
    suffix = f"  {marker_str}" if marker_str else ""
    return f"  {fname} : {sf_type}{suffix}"


_PLANTUML_REL = {
    "reference": '"1" -- "*"',
    "masterdetail": '"1" *-- "*"',
}


def _render_plantuml(
    objects_map: dict[str, dict[str, Any]],
    edges: list[tuple[str, str, str, str, bool]],
    include_fields: bool,
    field_filter: str,
    max_fields: int,
) -> str:
    lines = ["@startuml"]
    self_ref_notes: list[str] = []

    # Classes
    for obj_name in sorted(objects_map):
        obj = objects_map[obj_name]
        node_id = _safe_id(obj_name)
        label = obj.get("label", obj_name)
        if include_fields:
            selected, truncated, total = select_fields(obj, field_filter, max_fields)
            lines.append(f'class {node_id} as "{label}" {{')
            for f in selected:
                lines.append(_plantuml_field_line(f))
            if truncated:
                shown = len(selected)
                omitted = total - shown
                lines.append(f"  .. {shown} shown, {omitted} omitted ({total} total) ..")
            lines.append("}")
        else:
            lines.append(f'class {node_id} as "{label}" {{')
            lines.append("}")

    lines.append("")

    # Relationships
    seen_pairs: set[tuple[str, str, str]] = set()
    for from_obj, to_obj, rel_type, field_name, is_self_ref in edges:
        if is_self_ref:
            obj_label = objects_map.get(from_obj, {}).get("label", from_obj)
            self_ref_notes.append(
                f'note "{obj_label}.{field_name} -> {obj_label} '
                f'(self-referencing)" as N_{_safe_id(from_obj)}_{field_name}'
            )
            continue
        pair = (min(from_obj, to_obj), max(from_obj, to_obj), field_name)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        from_id = _safe_id(from_obj)
        to_id = _safe_id(to_obj)
        rel_sym = _PLANTUML_REL.get(rel_type, '"*" -- "*"')
        lines.append(f'{to_id} {rel_sym} {from_id} : {field_name}')

    if self_ref_notes:
        lines.append("")
        for note in self_ref_notes:
            lines.append(note)

    lines.append("")
    lines.append("@enduml")
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_er_diagram(
    objects_map: dict[str, dict[str, Any]],
    edges: list[tuple[str, str, str, str, bool]],
    include_fields: bool = True,
    field_filter: Literal["all", "required", "relationships"] = "relationships",
    max_fields: int = 20,
    format: Literal["mermaid", "plantuml"] = "mermaid",
) -> str:
    """Generate an ER diagram from pre-collected graph data.

    Args:
        objects_map: ``{api_name: object_dict}`` for objects to render.
        edges: List of ``(from, to, rel_type, field_name, is_self_ref)``.
        include_fields: Show fields inside entity blocks.
        field_filter: ``"all"`` | ``"required"`` | ``"relationships"``.
        max_fields: Max fields per entity block before truncation.
        format: ``"mermaid"`` or ``"plantuml"``.

    Returns:
        Diagram source text.
    """
    if format == "plantuml":
        return _render_plantuml(objects_map, edges, include_fields, field_filter, max_fields)
    return _render_mermaid(objects_map, edges, include_fields, field_filter, max_fields)


def generate_hierarchy_diagram(
    object_name: str,
    objects_map: dict[str, dict[str, Any]],
    max_levels: int = 3,
    format: Literal["mermaid", "plantuml"] = "mermaid",
) -> str:
    """Generate a hierarchy diagram for a self-referencing object.

    Args:
        object_name: The SObject API name.
        objects_map: Must contain *object_name* key.
        max_levels: Depth of hierarchy levels to show (1-6).
        format: ``"mermaid"`` or ``"plantuml"``.

    Returns:
        Diagram source text, or an error string if not hierarchical.
    """
    obj = objects_map.get(object_name)
    if not obj:
        return f"Object '{object_name}' not found in objects_map."

    # Find self-referencing fields
    self_ref_fields = [
        f for f in obj.get("fields", [])
        if f["type"] in ("reference", "masterdetail")
        and object_name in f.get("reference_to", [])
    ]
    if not self_ref_fields:
        return (
            f"Object '{object_name}' has no self-referencing lookup fields. "
            f"Use generate_er_diagram instead."
        )

    label = obj.get("label", object_name)

    # Key display fields
    name_fields = [
        f["name"] for f in obj.get("fields", [])
        if f["name"] in ("Name", "Subject", "Title")
        or (
            f.get("required")
            and f["name"] != "Id"
            and f["type"] not in ("reference", "masterdetail")
        )
    ][:3]

    if format == "plantuml":
        return _hierarchy_plantuml(object_name, label, self_ref_fields, name_fields, max_levels)
    return _hierarchy_mermaid(object_name, label, self_ref_fields, name_fields, max_levels)


def _hierarchy_mermaid(
    object_name: str,
    label: str,
    self_ref_fields: list[dict[str, Any]],
    name_fields: list[str],
    max_levels: int,
) -> str:
    lines = [
        "flowchart TD",
        f"    %% Hierarchy diagram: {label} ({object_name})",
        f"    %% Self-referencing fields: {', '.join(f['name'] for f in self_ref_fields)}",
        "",
    ]

    for level in range(max_levels + 1):
        node_id = f"L{level}"
        if level == 0:
            level_label = f"{label}\\n(Root / Top Level)"
        elif level == max_levels:
            level_label = f"{label}\\n(Level {level} — Leaf)"
        else:
            level_label = f"{label}\\n(Level {level})"
        if name_fields:
            level_label += f"\\nFields: {' | '.join(name_fields)}"
        lines.append(f'    {node_id}["{level_label}"]')

    lines.append("")

    for f in self_ref_fields:
        rel_type = "Master-Detail" if f["type"] == "masterdetail" else "Lookup"
        for level in range(max_levels):
            lines.append(
                f'    L{level} -->|"{f["name"]} ({rel_type})"| L{level + 1}'
            )

    lines.append("")
    lines.append(f"    style L0 fill:#1a73e8,color:#fff,stroke:#1557b0")
    lines.append(f"    style L{max_levels} fill:#34a853,color:#fff,stroke:#1e7e34")
    for level in range(1, max_levels):
        lines.append(f"    style L{level} fill:#f8f9fa,stroke:#dadce0,color:#202124")

    return "\n".join(lines)


def _hierarchy_plantuml(
    object_name: str,
    label: str,
    self_ref_fields: list[dict[str, Any]],
    name_fields: list[str],
    max_levels: int,
) -> str:
    lines = ["@startuml"]

    for level in range(max_levels + 1):
        node_id = f"L{level}"
        if level == 0:
            level_label = f"{label} (Root)"
        elif level == max_levels:
            level_label = f"{label} (Level {level} - Leaf)"
        else:
            level_label = f"{label} (Level {level})"
        lines.append(f'rectangle "{level_label}" as {node_id}')

    lines.append("")

    for f in self_ref_fields:
        rel_type = "Master-Detail" if f["type"] == "masterdetail" else "Lookup"
        for level in range(max_levels):
            lines.append(f'L{level} --> L{level + 1} : {f["name"]} ({rel_type})')

    for f in self_ref_fields:
        lines.append(
            f'note "{label}.{f["name"]} is a self-referencing '
            f'{f["type"]}" as N_{f["name"]}'
        )

    lines.append("")
    lines.append("@enduml")
    return "\n".join(lines)

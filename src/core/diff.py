"""
diff.py — Deterministic schema diff between two snapshots.

Pure structural comparison — no ML, no embeddings.  Produces a typed
``DiffResult`` with categorised changes and rule-based severity.
ML severity classification will replace the rule engine in Phase 4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FieldChange:
    """A single field-level change between two snapshot versions."""

    object_name: str
    field_name: str
    change_type: str   # ADDED | REMOVED | TYPE_CHANGED | REF_CHANGED | REQUIRED_CHANGED
    old_value: Any
    new_value: Any
    severity: str      # BREAKING | NON_BREAKING | INFO  (rule-based in Phase 1)

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON / MCP output."""
        return {
            "object_name": self.object_name,
            "field_name": self.field_name,
            "change_type": self.change_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "severity": self.severity,
        }


@dataclass
class ObjectDiff:
    """Aggregated changes for a single modified object."""

    object_name: str
    added_fields: list[FieldChange] = field(default_factory=list)
    removed_fields: list[FieldChange] = field(default_factory=list)
    type_changes: list[FieldChange] = field(default_factory=list)
    relationship_changes: list[FieldChange] = field(default_factory=list)
    other_changes: list[FieldChange] = field(default_factory=list)

    @property
    def all_changes(self) -> list[FieldChange]:
        return (
            self.added_fields
            + self.removed_fields
            + self.type_changes
            + self.relationship_changes
            + self.other_changes
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name,
            "added_fields": [c.as_dict() for c in self.added_fields],
            "removed_fields": [c.as_dict() for c in self.removed_fields],
            "type_changes": [c.as_dict() for c in self.type_changes],
            "relationship_changes": [c.as_dict() for c in self.relationship_changes],
            "other_changes": [c.as_dict() for c in self.other_changes],
        }


@dataclass
class DiffResult:
    """Full diff between two schema snapshots."""

    added_objects: list[str] = field(default_factory=list)
    removed_objects: list[str] = field(default_factory=list)
    modified_objects: dict[str, ObjectDiff] = field(default_factory=dict)
    added_fields: dict[str, list[FieldChange]] = field(default_factory=dict)
    removed_fields: dict[str, list[FieldChange]] = field(default_factory=dict)
    type_changes: dict[str, list[FieldChange]] = field(default_factory=dict)
    relationship_changes: dict[str, list[FieldChange]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    breaking_candidates: list[FieldChange] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialise the entire diff to a dict suitable for JSON output."""
        return {
            "added_objects": self.added_objects,
            "removed_objects": self.removed_objects,
            "modified_objects": {k: v.as_dict() for k, v in self.modified_objects.items()},
            "added_fields": {k: [c.as_dict() for c in v] for k, v in self.added_fields.items()},
            "removed_fields": {k: [c.as_dict() for c in v] for k, v in self.removed_fields.items()},
            "type_changes": {k: [c.as_dict() for c in v] for k, v in self.type_changes.items()},
            "relationship_changes": {k: [c.as_dict() for c in v] for k, v in self.relationship_changes.items()},
            "summary": self.summary,
            "breaking_candidates": [c.as_dict() for c in self.breaking_candidates],
        }

    def as_text_report(self) -> str:
        """Human-readable multi-line diff report."""
        lines: list[str] = ["Schema Diff Report", "=" * 60]

        # Summary counts
        lines.append("")
        lines.append("Summary:")
        for key, val in self.summary.items():
            lines.append(f"  {key}: {val}")

        # Added objects
        if self.added_objects:
            lines.append("")
            lines.append("Added Objects:")
            for name in sorted(self.added_objects):
                lines.append(f"  + {name}")

        # Removed objects
        if self.removed_objects:
            lines.append("")
            lines.append("Removed Objects:")
            for name in sorted(self.removed_objects):
                lines.append(f"  - {name}")

        # Modified objects
        if self.modified_objects:
            lines.append("")
            lines.append("Modified Objects:")
            for obj_name in sorted(self.modified_objects):
                obj_diff = self.modified_objects[obj_name]
                lines.append(f"  {obj_name}:")
                for change in obj_diff.all_changes:
                    marker = _severity_marker(change.severity)
                    lines.append(
                        f"    {marker} {change.field_name}: "
                        f"{change.change_type} "
                        f"({change.old_value} -> {change.new_value})"
                    )

        # Breaking candidates
        if self.breaking_candidates:
            lines.append("")
            lines.append("Breaking Change Candidates:")
            # Phase 4 placeholder: ML severity classifier replaces rules here
            for change in self.breaking_candidates:
                lines.append(
                    f"  !! {change.object_name}.{change.field_name}: "
                    f"{change.change_type} "
                    f"({change.old_value} -> {change.new_value})"
                )

        return "\n".join(lines)


# ── Severity rules (Phase 1 — will be replaced by ML in Phase 4) ─────────────

# Incompatible type transitions: old_type -> set of new_types considered breaking.
_INCOMPATIBLE_TYPE_CHANGES: dict[str, set[str]] = {
    "string": {"boolean", "double", "int", "date", "datetime"},
    "textarea": {"boolean", "double", "int", "date", "datetime", "string"},
    "double": {"boolean", "string", "date", "datetime"},
    "int": {"boolean", "string", "date", "datetime"},
    "currency": {"boolean", "string", "date", "datetime"},
    "percent": {"boolean", "string", "date", "datetime"},
    "date": {"boolean", "string", "double", "int"},
    "datetime": {"boolean", "string", "double", "int"},
    "boolean": {"string", "double", "int", "date", "datetime"},
    "reference": {"string", "boolean", "double", "int"},
    "masterdetail": {"string", "boolean", "double", "int"},
    "picklist": {"boolean", "double", "int", "date", "datetime"},
    "multipicklist": {"boolean", "double", "int", "date", "datetime", "string"},
}


def _classify_severity(change_type: str, old_value: Any, new_value: Any) -> str:
    """Rule-based severity classification.

    Phase 4 will replace this with an ML classifier.

    Rules:
        BREAKING:     field removed, type changed incompatibly,
                      required=True added (was optional).
        NON_BREAKING: field added, nullable changed to nullable, label changed.
        INFO:         object added, description changed, label changed.
    """
    if change_type == "REMOVED":
        return "BREAKING"

    if change_type == "TYPE_CHANGED":
        old_t = str(old_value).lower() if old_value else ""
        new_t = str(new_value).lower() if new_value else ""
        incompat = _INCOMPATIBLE_TYPE_CHANGES.get(old_t, set())
        if new_t in incompat:
            return "BREAKING"
        return "NON_BREAKING"

    if change_type == "REQUIRED_CHANGED":
        # Was optional, now required → breaking
        if new_value is True and old_value is not True:
            return "BREAKING"
        return "NON_BREAKING"

    if change_type == "REF_CHANGED":
        return "NON_BREAKING"

    if change_type == "ADDED":
        return "NON_BREAKING"

    return "INFO"


def _severity_marker(severity: str) -> str:
    if severity == "BREAKING":
        return "!!"
    if severity == "NON_BREAKING":
        return " +"
    return "  "


# ── Diff engine ───────────────────────────────────────────────────────────────

def _diff_fields(
    object_name: str,
    fields_a: list[dict[str, Any]],
    fields_b: list[dict[str, Any]],
) -> list[FieldChange]:
    """Compare field lists for a single object and return changes."""
    map_a = {f["name"]: f for f in fields_a}
    map_b = {f["name"]: f for f in fields_b}

    changes: list[FieldChange] = []

    # Removed fields
    for fname in sorted(set(map_a) - set(map_b)):
        fa = map_a[fname]
        changes.append(FieldChange(
            object_name=object_name,
            field_name=fname,
            change_type="REMOVED",
            old_value=fa["type"],
            new_value=None,
            severity=_classify_severity("REMOVED", fa["type"], None),
        ))

    # Added fields
    for fname in sorted(set(map_b) - set(map_a)):
        fb = map_b[fname]
        changes.append(FieldChange(
            object_name=object_name,
            field_name=fname,
            change_type="ADDED",
            old_value=None,
            new_value=fb["type"],
            severity=_classify_severity("ADDED", None, fb["type"]),
        ))

    # Modified fields (present in both)
    for fname in sorted(set(map_a) & set(map_b)):
        fa, fb = map_a[fname], map_b[fname]

        # Type change
        if fa["type"] != fb["type"]:
            changes.append(FieldChange(
                object_name=object_name,
                field_name=fname,
                change_type="TYPE_CHANGED",
                old_value=fa["type"],
                new_value=fb["type"],
                severity=_classify_severity("TYPE_CHANGED", fa["type"], fb["type"]),
            ))

        # Reference target change
        old_refs = sorted(fa.get("reference_to") or [])
        new_refs = sorted(fb.get("reference_to") or [])
        if old_refs != new_refs:
            changes.append(FieldChange(
                object_name=object_name,
                field_name=fname,
                change_type="REF_CHANGED",
                old_value=old_refs,
                new_value=new_refs,
                severity=_classify_severity("REF_CHANGED", old_refs, new_refs),
            ))

        # Required change
        old_req = fa.get("required", False)
        new_req = fb.get("required", False)
        if old_req != new_req:
            changes.append(FieldChange(
                object_name=object_name,
                field_name=fname,
                change_type="REQUIRED_CHANGED",
                old_value=old_req,
                new_value=new_req,
                severity=_classify_severity("REQUIRED_CHANGED", old_req, new_req),
            ))

    return changes


def compare_snapshots(
    snapshot_a: dict[str, dict[str, Any]],
    snapshot_b: dict[str, dict[str, Any]],
) -> DiffResult:
    """Compare two full schema snapshots and produce a structured diff.

    Args:
        snapshot_a: "Before" snapshot — ``{api_name: object_dict}``.
        snapshot_b: "After" snapshot.

    Returns:
        :class:`DiffResult` with all categorised changes.
    """
    names_a = set(snapshot_a)
    names_b = set(snapshot_b)

    result = DiffResult(
        added_objects=sorted(names_b - names_a),
        removed_objects=sorted(names_a - names_b),
    )

    # Compare objects present in both snapshots
    for obj_name in sorted(names_a & names_b):
        fields_a = snapshot_a[obj_name].get("fields", [])
        fields_b = snapshot_b[obj_name].get("fields", [])
        changes = _diff_fields(obj_name, fields_a, fields_b)
        if not changes:
            continue

        obj_diff = ObjectDiff(object_name=obj_name)
        for c in changes:
            if c.change_type == "ADDED":
                obj_diff.added_fields.append(c)
                result.added_fields.setdefault(obj_name, []).append(c)
            elif c.change_type == "REMOVED":
                obj_diff.removed_fields.append(c)
                result.removed_fields.setdefault(obj_name, []).append(c)
            elif c.change_type == "TYPE_CHANGED":
                obj_diff.type_changes.append(c)
                result.type_changes.setdefault(obj_name, []).append(c)
            elif c.change_type == "REF_CHANGED":
                obj_diff.relationship_changes.append(c)
                result.relationship_changes.setdefault(obj_name, []).append(c)
            else:
                obj_diff.other_changes.append(c)

            if c.severity == "BREAKING":
                result.breaking_candidates.append(c)

        result.modified_objects[obj_name] = obj_diff

    # Build summary counts
    total_changes = sum(
        len(od.all_changes) for od in result.modified_objects.values()
    )
    result.summary = {
        "objects_added": len(result.added_objects),
        "objects_removed": len(result.removed_objects),
        "objects_modified": len(result.modified_objects),
        "total_field_changes": total_changes,
        "breaking_candidates": len(result.breaking_candidates),
        "fields_added": sum(len(v) for v in result.added_fields.values()),
        "fields_removed": sum(len(v) for v in result.removed_fields.values()),
        "type_changes": sum(len(v) for v in result.type_changes.values()),
        "relationship_changes": sum(len(v) for v in result.relationship_changes.values()),
    }

    return result

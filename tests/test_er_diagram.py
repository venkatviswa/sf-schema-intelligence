"""Tests for src.core.er_diagram — Mermaid and PlantUML renderers."""
from __future__ import annotations

from src.core.er_diagram import (
    generate_er_diagram,
    generate_hierarchy_diagram,
    select_fields,
)
from src.core.graph import build_graph, collect_subgraph


class TestSelectFields:
    """Field selection and truncation logic."""

    def test_id_always_first(self, snapshot_v1):
        obj = snapshot_v1["Account"]
        selected, _, _ = select_fields(obj, field_filter="relationships", max_fields=5)
        assert selected[0]["name"] == "Id"

    def test_external_id_included(self, snapshot_v1):
        obj = snapshot_v1["Account"]
        selected, _, _ = select_fields(obj, field_filter="relationships", max_fields=20)
        names = [f["name"] for f in selected]
        assert "ExternalId__c" in names

    def test_relationship_fields_included(self, snapshot_v1):
        obj = snapshot_v1["HealthCloudGA__CarePlan__c"]
        selected, _, _ = select_fields(obj, field_filter="relationships", max_fields=20)
        names = [f["name"] for f in selected]
        assert "HealthCloudGA__Account__c" in names
        assert "HealthCloudGA__Patient__c" in names

    def test_truncation_on_large_object(self, snapshot_v1):
        obj = snapshot_v1["Account"]
        selected, truncated, total = select_fields(obj, field_filter="relationships", max_fields=5)
        assert truncated is True
        assert len(selected) <= 5
        assert total == len(obj["fields"])

    def test_no_truncation_on_small_object_all_filter(self, snapshot_v1):
        obj = snapshot_v1["HealthCloudGA__CareProgram__c"]  # 4 fields
        selected, truncated, total = select_fields(obj, field_filter="all", max_fields=20)
        assert truncated is False
        assert len(selected) == total

    def test_required_fields_included(self, snapshot_v1):
        obj = snapshot_v1["HealthCloudGA__CarePlan__c"]
        selected, _, _ = select_fields(obj, field_filter="relationships", max_fields=20)
        names = [f["name"] for f in selected]
        # Name is required
        assert "Name" in names

    def test_field_filter_all_fills_remaining(self, snapshot_v1):
        obj = snapshot_v1["Account"]
        selected, _, total = select_fields(obj, field_filter="all", max_fields=20)
        assert len(selected) <= 20
        # Should have more fields than just relationships
        rel_only, _, _ = select_fields(obj, field_filter="relationships", max_fields=20)
        assert len(selected) >= len(rel_only)


class TestMermaidRenderer:
    """Mermaid ER diagram output."""

    def test_starts_with_er_diagram(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=1)
        result = generate_er_diagram(objects_map, edges, format="mermaid")
        assert result.startswith("erDiagram")

    def test_entity_blocks_present(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["HealthCloudGA__CarePlan__c"], depth=0)
        result = generate_er_diagram(objects_map, edges, format="mermaid")
        assert "HealthCloudGA_CarePlan_c" in result  # safe_id version

    def test_relationship_lines_present(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["HealthCloudGA__CarePlan__c"], depth=1)
        result = generate_er_diagram(objects_map, edges, format="mermaid")
        # Should have relationship arrows
        assert "||--o{" in result or "||--|{" in result

    def test_self_ref_rendered_as_comment(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=1, direction="both")
        result = generate_er_diagram(objects_map, edges, format="mermaid")
        assert "%% SELF-REF:" in result

    def test_no_fields_mode(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=1)
        result = generate_er_diagram(objects_map, edges, include_fields=False, format="mermaid")
        # Should still have entities but only Id
        assert "string Id PK" in result

    def test_truncation_note_for_large_object(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=0)
        result = generate_er_diagram(
            objects_map, edges,
            include_fields=True, field_filter="relationships", max_fields=3,
            format="mermaid",
        )
        assert "shown" in result and "omitted" in result


class TestPlantUMLRenderer:
    """PlantUML ER diagram output."""

    def test_starts_and_ends_correctly(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=1)
        result = generate_er_diagram(objects_map, edges, format="plantuml")
        assert result.startswith("@startuml")
        assert result.strip().endswith("@enduml")

    def test_class_blocks_present(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["HealthCloudGA__CarePlan__c"], depth=0)
        result = generate_er_diagram(objects_map, edges, format="plantuml")
        assert "class HealthCloudGA_CarePlan_c" in result

    def test_self_ref_note_present(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=1, direction="both")
        result = generate_er_diagram(objects_map, edges, format="plantuml")
        assert "self-referencing" in result

    def test_truncation_separator_for_large_object(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=0)
        result = generate_er_diagram(
            objects_map, edges,
            include_fields=True, field_filter="relationships", max_fields=3,
            format="plantuml",
        )
        assert "shown" in result and "omitted" in result


class TestHierarchyDiagram:
    """Hierarchy diagram for self-referencing objects."""

    def test_mermaid_hierarchy_for_account(self, snapshot_v1):
        result = generate_hierarchy_diagram("Account", snapshot_v1, max_levels=3, format="mermaid")
        assert "flowchart TD" in result
        assert "L0" in result
        assert "L3" in result
        assert "ParentId" in result

    def test_plantuml_hierarchy_for_account(self, snapshot_v1):
        result = generate_hierarchy_diagram("Account", snapshot_v1, max_levels=2, format="plantuml")
        assert "@startuml" in result
        assert "@enduml" in result
        assert "ParentId" in result

    def test_non_hierarchical_object_returns_error(self, snapshot_v1):
        result = generate_hierarchy_diagram(
            "HealthCloudGA__CareProgram__c", snapshot_v1, format="mermaid",
        )
        assert "no self-referencing" in result

    def test_missing_object_returns_error(self, snapshot_v1):
        result = generate_hierarchy_diagram("DoesNotExist__c", snapshot_v1, format="mermaid")
        assert "not found" in result

    def test_care_plan_self_ref_hierarchy(self, snapshot_v1):
        """CarePlan has a ParentCarePlan self-ref."""
        result = generate_hierarchy_diagram(
            "HealthCloudGA__CarePlan__c", snapshot_v1, max_levels=2, format="mermaid",
        )
        assert "flowchart TD" in result
        assert "HealthCloudGA__ParentCarePlan__c" in result

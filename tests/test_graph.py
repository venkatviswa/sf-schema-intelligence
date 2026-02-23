"""Tests for src.core.graph — relationship graph construction and traversal."""
from __future__ import annotations

from src.core.graph import (
    INBOUND_NOISE_FIELDS,
    INBOUND_NOISE_OBJECTS,
    SKIP_OBJECTS,
    build_graph,
    collect_subgraph,
    get_neighbors,
)


# ── Fixtures helpers ─────────────────────────────────────────────────────────

def _make_obj(name, fields=None, custom=False):
    """Minimal object dict for test snapshots."""
    return {
        "name": name,
        "label": name,
        "custom": custom,
        "fields": fields or [],
        "child_relationships": [],
    }


def _ref_field(name, ref_to):
    return {"name": name, "type": "reference", "reference_to": [ref_to], "required": False}


def _md_field(name, ref_to):
    return {"name": name, "type": "masterdetail", "reference_to": [ref_to], "required": True}


# ── Existing tests (unchanged) ────────────────────────────────────────────────


class TestBuildGraph:
    """Graph construction from snapshots."""

    def test_nodes_created_for_all_non_skip_objects(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        for obj_name in snapshot_v1:
            if obj_name not in SKIP_OBJECTS:
                assert obj_name in g.nodes, f"{obj_name} missing from graph"

    def test_skip_objects_excluded(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        for skip_name in SKIP_OBJECTS:
            assert skip_name not in g.nodes

    def test_relationship_edges_created(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        edges = [
            (u, v) for u, v, d in g.edges(data=True)
            if u == "HealthCloudGA__CarePlan__c" and v == "Account"
        ]
        assert len(edges) >= 1

    def test_master_detail_edge_has_correct_type(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        for u, v, d in g.edges(data=True):
            if u == "HealthCloudGA__CarePlanGoal__c" and v == "HealthCloudGA__CarePlan__c":
                assert d["rel_type"] == "masterdetail"
                break
        else:
            raise AssertionError("Master-detail edge not found")

    def test_self_referencing_edge(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        self_edges = [
            (u, v, d) for u, v, d in g.edges(data=True)
            if u == v == "Account"
        ]
        assert len(self_edges) >= 1
        assert self_edges[0][2]["self_ref"] is True

    def test_contact_self_ref(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        self_edges = [
            (u, v, d) for u, v, d in g.edges(data=True)
            if u == v == "Contact"
        ]
        assert len(self_edges) >= 1

    # ── New: is_noise edge attribute ─────────────────────────────────────────

    def test_noise_field_edge_marked_as_noise(self):
        """Edges via OwnerId / CreatedById must have is_noise=True."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("OwnerId", "User"),
                _ref_field("CreatedById", "User"),
            ]),
            "User": _make_obj("User"),
        }
        g = build_graph(snapshot)
        for u, v, d in g.edges(data=True):
            if u == "HealthcareProvider" and d["field"] in INBOUND_NOISE_FIELDS:
                assert d["is_noise"] is True, f"Expected is_noise=True for {d['field']}"

    def test_noise_object_edge_marked_as_noise(self):
        """Edges from a noise object (e.g. EmailMessage) must be marked."""
        snapshot = {
            "Account": _make_obj("Account"),
            "EmailMessage": _make_obj("EmailMessage", fields=[
                _ref_field("RelatedToId", "Account"),
            ]),
        }
        g = build_graph(snapshot)
        for u, v, d in g.edges(data=True):
            if u == "EmailMessage" and v == "Account":
                assert d["is_noise"] is True

    def test_domain_edge_not_marked_as_noise(self):
        """A normal business relationship must have is_noise=False."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
            ]),
            "Account": _make_obj("Account"),
        }
        g = build_graph(snapshot)
        for u, v, d in g.edges(data=True):
            if u == "HealthcareProvider" and v == "Account":
                assert d["is_noise"] is False

    def test_masterdetail_edge_not_noise(self):
        """Master-detail relationships are always domain relationships."""
        snapshot = {
            "Accreditation__c": _make_obj("Accreditation__c", fields=[
                _md_field("HealthcareProviderId__c", "HealthcareProvider"),
            ]),
            "HealthcareProvider": _make_obj("HealthcareProvider"),
        }
        g = build_graph(snapshot)
        for u, v, d in g.edges(data=True):
            if u == "Accreditation__c" and v == "HealthcareProvider":
                assert d["is_noise"] is False


class TestGetNeighbors:
    """Neighbor discovery and direction filtering."""

    def test_outbound_neighbors_of_care_plan(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "HealthCloudGA__CarePlan__c", direction="outbound", depth=1)
        assert "Account" in neighbors
        assert "Contact" in neighbors
        assert "HealthCloudGA__CareProgram__c" in neighbors

    def test_inbound_neighbors_of_care_plan(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "HealthCloudGA__CarePlan__c", direction="inbound", depth=1)
        assert "HealthCloudGA__CarePlanGoal__c" in neighbors
        assert "HealthCloudGA__CareTeamMember__c" in neighbors

    def test_both_direction(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "HealthCloudGA__CarePlan__c", direction="both", depth=1)
        assert "Account" in neighbors
        assert "HealthCloudGA__CarePlanGoal__c" in neighbors

    def test_depth_two_reaches_further(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        d1 = get_neighbors(g, "HealthCloudGA__CarePlanGoal__c", direction="outbound", depth=1)
        d2 = get_neighbors(g, "HealthCloudGA__CarePlanGoal__c", direction="outbound", depth=2)
        assert d1.issubset(d2)
        assert "Account" in d2

    def test_depth_zero_returns_empty(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "Account", direction="both", depth=0)
        assert neighbors == set()

    def test_nonexistent_object_returns_empty(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "DoesNotExist__c", direction="both", depth=1)
        assert neighbors == set()

    def test_self_ref_not_in_neighbors(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "Account", direction="both", depth=1)
        assert "Account" not in neighbors

    # ── New: noise filtering in inbound traversal ─────────────────────────────

    def test_noise_objects_excluded_from_both_traversal(self):
        """EmailMessage and other noise objects must not appear in direction=both."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
            ]),
            "Account": _make_obj("Account"),
            "EmailMessage": _make_obj("EmailMessage", fields=[
                _ref_field("RelatedToId", "HealthcareProvider"),
            ]),
            "Accreditation__c": _make_obj("Accreditation__c", fields=[
                _ref_field("HealthcareProviderId__c", "HealthcareProvider"),
            ]),
        }
        g = build_graph(snapshot)
        neighbors = get_neighbors(g, "HealthcareProvider", direction="both", depth=1)
        assert "EmailMessage" not in neighbors
        assert "Account" in neighbors           # outbound — still present
        assert "Accreditation__c" in neighbors  # meaningful inbound — still present

    def test_noise_fields_excluded_from_inbound_traversal(self):
        """Objects that reference a target only via OwnerId should be excluded."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
            ]),
            "Account": _make_obj("Account"),
            "SomeObject__c": _make_obj("SomeObject__c", fields=[
                _ref_field("OwnerId", "HealthcareProvider"),   # noise field
            ]),
        }
        g = build_graph(snapshot)
        neighbors = get_neighbors(g, "HealthcareProvider", direction="inbound", depth=1)
        assert "SomeObject__c" not in neighbors

    def test_noise_object_excluded_inbound_only(self):
        """Noise objects should be excluded inbound but not affect outbound."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
            ]),
            "Account": _make_obj("Account"),
            "FlowRecordRelation": _make_obj("FlowRecordRelation", fields=[
                _ref_field("RelatedRecordId", "HealthcareProvider"),
            ]),
        }
        g = build_graph(snapshot)
        inbound = get_neighbors(g, "HealthcareProvider", direction="inbound", depth=1)
        outbound = get_neighbors(g, "HealthcareProvider", direction="outbound", depth=1)
        assert "FlowRecordRelation" not in inbound
        assert "Account" in outbound  # outbound unaffected

    def test_both_direction_yields_meaningful_objects_only(self):
        """direction=both should return domain objects, not platform noise."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
                _ref_field("PractitionerId", "Contact"),
            ]),
            "Account": _make_obj("Account"),
            "Contact": _make_obj("Contact"),
            "Accreditation__c": _make_obj("Accreditation__c", fields=[
                _ref_field("ProviderId__c", "HealthcareProvider"),
            ]),
            "BoardCertification__c": _make_obj("BoardCertification__c", fields=[
                _ref_field("ProviderId__c", "HealthcareProvider"),
            ]),
            "AIInsightValue": _make_obj("AIInsightValue", fields=[
                _ref_field("RelatedEntityId", "HealthcareProvider"),
            ]),
            "EmailMessage": _make_obj("EmailMessage", fields=[
                _ref_field("RelatedToId", "HealthcareProvider"),
            ]),
        }
        g = build_graph(snapshot)
        neighbors = get_neighbors(g, "HealthcareProvider", direction="both", depth=1)

        # Domain relationships preserved
        assert "Account" in neighbors
        assert "Contact" in neighbors
        assert "Accreditation__c" in neighbors
        assert "BoardCertification__c" in neighbors

        # Noise excluded
        assert "AIInsightValue" not in neighbors
        assert "EmailMessage" not in neighbors

    def test_outbound_direction_unaffected_by_noise_filter(self):
        """Noise filtering must never remove outbound edges."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("OwnerId", "User"),        # noise field — outbound
                _ref_field("AccountId", "Account"),   # domain field — outbound
            ]),
            "Account": _make_obj("Account"),
            "User": _make_obj("User"),
        }
        g = build_graph(snapshot)
        # User is in SKIP_OBJECTS so won't appear, but Account must
        neighbors = get_neighbors(g, "HealthcareProvider", direction="outbound", depth=1)
        assert "Account" in neighbors


class TestCollectSubgraph:
    """Subgraph extraction for diagram rendering."""

    def test_subgraph_includes_root(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=1)
        assert "Account" in objects_map

    def test_subgraph_edges_match_nodes(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["HealthCloudGA__CarePlan__c"], depth=1)
        for from_obj, to_obj, *_ in edges:
            assert from_obj in objects_map or to_obj in objects_map

    def test_subgraph_depth_zero_single_object(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        objects_map, edges = collect_subgraph(g, ["Account"], depth=0)
        assert "Account" in objects_map
        external_edges = [(u, v) for u, v, *_ in edges if u != v]
        assert len(external_edges) == 0

    # ── New: noise filtering in collect_subgraph ──────────────────────────────

    def test_noise_objects_not_in_subgraph_nodes(self):
        """Noise objects must not appear in objects_map when using direction=both."""
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
            ]),
            "Account": _make_obj("Account"),
            "EmailMessage": _make_obj("EmailMessage", fields=[
                _ref_field("RelatedToId", "HealthcareProvider"),
            ]),
            "Accreditation__c": _make_obj("Accreditation__c", fields=[
                _ref_field("ProviderId__c", "HealthcareProvider"),
            ]),
        }
        g = build_graph(snapshot)
        objects_map, edges = collect_subgraph(
            g, ["HealthcareProvider"], depth=1, direction="both"
        )
        assert "EmailMessage" not in objects_map
        assert "Account" in objects_map
        assert "Accreditation__c" in objects_map

    def test_subgraph_object_count_reduced_with_noise_filter(self):
        """direction=both with noise filter must produce far fewer objects than without."""
        noise_objects = {
            name: _make_obj(name, fields=[_ref_field("RelatedId", "HealthcareProvider")])
            for name in list(INBOUND_NOISE_OBJECTS)[:6]
        }
        domain_objects = {
            "Accreditation__c": _make_obj("Accreditation__c", fields=[
                _ref_field("ProviderId__c", "HealthcareProvider"),
            ]),
            "BoardCertification__c": _make_obj("BoardCertification__c", fields=[
                _ref_field("ProviderId__c", "HealthcareProvider"),
            ]),
        }
        snapshot = {
            "HealthcareProvider": _make_obj("HealthcareProvider", fields=[
                _ref_field("AccountId", "Account"),
            ]),
            "Account": _make_obj("Account"),
            **noise_objects,
            **domain_objects,
        }
        g = build_graph(snapshot)
        objects_map, _ = collect_subgraph(
            g, ["HealthcareProvider"], depth=1, direction="both"
        )
        # Should have: HealthcareProvider + Account + 2 domain objects = 4
        # Must NOT have 6 noise objects added
        assert len(objects_map) <= 4
        for noise_name in noise_objects:
            assert noise_name not in objects_map
"""Tests for src.core.graph — relationship graph construction and traversal."""
from __future__ import annotations

from src.core.graph import SKIP_OBJECTS, build_graph, collect_subgraph, get_neighbors


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
        # CarePlan -> Account via HealthCloudGA__Account__c
        edges = [
            (u, v) for u, v, d in g.edges(data=True)
            if u == "HealthCloudGA__CarePlan__c" and v == "Account"
        ]
        assert len(edges) >= 1

    def test_master_detail_edge_has_correct_type(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        # CarePlanGoal -> CarePlan via master-detail
        for u, v, d in g.edges(data=True):
            if u == "HealthCloudGA__CarePlanGoal__c" and v == "HealthCloudGA__CarePlan__c":
                assert d["rel_type"] == "masterdetail"
                break
        else:
            raise AssertionError("Master-detail edge not found")

    def test_self_referencing_edge(self, snapshot_v1):
        """Account.ParentId -> Account should produce a self-ref edge."""
        g = build_graph(snapshot_v1)
        self_edges = [
            (u, v, d) for u, v, d in g.edges(data=True)
            if u == v == "Account"
        ]
        assert len(self_edges) >= 1
        assert self_edges[0][2]["self_ref"] is True

    def test_contact_self_ref(self, snapshot_v1):
        """Contact.ReportsToId -> Contact is a self-referencing lookup."""
        g = build_graph(snapshot_v1)
        self_edges = [
            (u, v, d) for u, v, d in g.edges(data=True)
            if u == v == "Contact"
        ]
        assert len(self_edges) >= 1


class TestGetNeighbors:
    """Neighbor discovery and direction filtering."""

    def test_outbound_neighbors_of_care_plan(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "HealthCloudGA__CarePlan__c", direction="outbound", depth=1)
        # CarePlan references Account, Contact, CareProgram, and itself
        assert "Account" in neighbors
        assert "Contact" in neighbors
        assert "HealthCloudGA__CareProgram__c" in neighbors

    def test_inbound_neighbors_of_care_plan(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "HealthCloudGA__CarePlan__c", direction="inbound", depth=1)
        # CarePlanGoal and CareTeamMember point to CarePlan
        assert "HealthCloudGA__CarePlanGoal__c" in neighbors
        assert "HealthCloudGA__CareTeamMember__c" in neighbors

    def test_both_direction(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "HealthCloudGA__CarePlan__c", direction="both", depth=1)
        # Should include both inbound and outbound
        assert "Account" in neighbors
        assert "HealthCloudGA__CarePlanGoal__c" in neighbors

    def test_depth_two_reaches_further(self, snapshot_v1):
        g = build_graph(snapshot_v1)
        d1 = get_neighbors(g, "HealthCloudGA__CarePlanGoal__c", direction="outbound", depth=1)
        d2 = get_neighbors(g, "HealthCloudGA__CarePlanGoal__c", direction="outbound", depth=2)
        # depth=2 should be a superset of depth=1
        assert d1.issubset(d2)
        # CarePlanGoal -> CarePlan -> Account (at depth 2)
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
        """The starting node should not appear in its own neighbor set."""
        g = build_graph(snapshot_v1)
        neighbors = get_neighbors(g, "Account", direction="both", depth=1)
        assert "Account" not in neighbors


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
        # depth=0 means no traversal, but self-ref edges within the root are included
        external_edges = [(u, v) for u, v, *_ in edges if u != v]
        assert len(external_edges) == 0

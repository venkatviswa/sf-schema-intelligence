"""
graph.py — Build a NetworkX relationship graph from a schema snapshot.

Nodes represent SObjects, edges represent relationships (lookup, master-detail,
child).  No MCP, no ML — pure graph construction and traversal.
"""
from __future__ import annotations

from typing import Any, Literal

import networkx as nx

# System / utility objects that clutter diagrams without adding domain value.
SKIP_OBJECTS: set[str] = {
    "User", "Group", "Profile", "PermissionSet", "RecordType",
    "BusinessHours", "Holiday", "NetworkMember", "CollaborationGroup",
    "FeedItem", "FeedComment", "ContentDocument", "ContentVersion",
    "ContentDocumentLink", "Task", "Event", "Note", "Attachment",
    "EntitySubscription", "ProcessInstance", "ProcessInstanceStep",
    "TopicAssignment", "Vote", "FlowInterview",
}

# Objects that produce inbound noise via polymorphic or platform-level
# relationships.  They reference almost every domain object but carry no
# domain meaning (e.g. every SObject has an EmailMessage child).
INBOUND_NOISE_OBJECTS: set[str] = {
    "EmailMessage", "OutgoingEmail", "TrackedCommunicationDetail",
    "AuthorNote", "EventRelation", "TaskRelation",
    "FlowRecordRelation", "FlowOrchestrationWorkItem",
    "AIInsightValue", "AIRecordInsight",
    "GenericVisitTaskContext", "PendingServiceRoutingInteractionInfo",
    "Identifier",
}

# Relationship fields that are present on virtually every SObject and add no
# domain value when followed inbound.
INBOUND_NOISE_FIELDS: set[str] = {
    "OwnerId", "CreatedById", "LastModifiedById",
    "RecordTypeId", "MasterRecordId",
}


def build_graph(snapshot: dict[str, dict[str, Any]]) -> nx.DiGraph:
    """Build a directed graph from a full schema snapshot.

    Each node is an SObject API name.  Each directed edge represents a
    relationship field pointing from the child/referencing object to the
    referenced (parent) object.

    Edge attributes:
        ``field``      — API name of the relationship field.
        ``rel_type``   — ``"reference"`` | ``"masterdetail"``.
        ``self_ref``   — ``True`` when source == target.
        ``is_noise``   — ``True`` when the edge originates from a noise
                         object or noise field and should be excluded from
                         inbound traversal.

    Nodes carry the full object dict under the ``data`` attribute.

    Args:
        snapshot: ``{api_name: object_dict}`` as returned by
            ``schema_cache.load_snapshot``.

    Returns:
        ``nx.DiGraph`` with SObject nodes and relationship edges.
    """
    g = nx.DiGraph()

    for obj_name, obj in snapshot.items():
        if obj_name in SKIP_OBJECTS:
            continue
        g.add_node(obj_name, data=obj)

    for obj_name, obj in snapshot.items():
        if obj_name in SKIP_OBJECTS:
            continue
        for field in obj.get("fields", []):
            if field["type"] not in ("reference", "masterdetail"):
                continue
            for ref_target in field.get("reference_to", []):
                if ref_target in SKIP_OBJECTS:
                    continue
                if ref_target not in g:
                    g.add_node(ref_target, data=snapshot.get(ref_target, {}))

                # Mark edge as noise if the source object or field is known
                # to produce inbound clutter.
                is_noise = (
                    obj_name in INBOUND_NOISE_OBJECTS
                    or field["name"] in INBOUND_NOISE_FIELDS
                )

                g.add_edge(
                    obj_name,
                    ref_target,
                    field=field["name"],
                    rel_type=field["type"],
                    self_ref=(obj_name == ref_target),
                    is_noise=is_noise,
                )

    return g


def get_neighbors(
    graph: nx.DiGraph,
    object_name: str,
    direction: Literal["both", "outbound", "inbound"] = "both",
    depth: int = 1,
) -> set[str]:
    """Return SObject names reachable from *object_name* within *depth* hops.

    When traversing inbound edges, noise edges (system audit fields and
    platform objects that reference almost every SObject) are excluded so
    that direction="both" returns meaningful domain relationships rather
    than the full platform graph.

    Args:
        graph: Graph built by :func:`build_graph`.
        object_name: Starting node.
        direction: ``"outbound"`` follows edges away from the node (this
            object references → parent), ``"inbound"`` follows edges
            coming in (child → this object), ``"both"`` follows both.
        depth: Maximum number of hops.

    Returns:
        Set of SObject API names (excludes *object_name* itself).
    """
    if object_name not in graph:
        return set()

    result: set[str] = set()
    frontier: set[str] = {object_name}

    for _ in range(depth):
        next_frontier: set[str] = set()
        for node in frontier:
            if direction in ("outbound", "both"):
                next_frontier.update(graph.successors(node))
            if direction in ("inbound", "both"):
                # Only follow inbound edges that carry domain meaning.
                next_frontier.update(
                    u for u, v, d in graph.in_edges(node, data=True)
                    if not d.get("is_noise", False)
                )
        next_frontier -= result
        next_frontier.discard(object_name)
        result.update(next_frontier)
        frontier = next_frontier

    return result


def collect_subgraph(
    graph: nx.DiGraph,
    root_objects: list[str],
    depth: int = 1,
    direction: Literal["both", "outbound", "inbound"] = "both",
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, str, str, bool]]]:
    """Extract a subgraph around *root_objects* for diagram rendering.

    Noise edges are excluded from inbound traversal (see :func:`get_neighbors`)
    but are still rendered if both endpoints happen to be in the subgraph.

    Returns:
        ``(objects_map, edges)`` where:
        - ``objects_map`` is ``{api_name: object_dict}``.
        - ``edges`` is a list of ``(from_obj, to_obj, rel_type, field_name,
          is_self_ref)`` tuples.
    """
    nodes: set[str] = set(root_objects)
    for root in root_objects:
        nodes.update(get_neighbors(graph, root, direction, depth))

    objects_map: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if n in graph.nodes:
            data = graph.nodes[n].get("data", {})
            if data:
                objects_map[n] = data

    edges: list[tuple[str, str, str, str, bool]] = []
    seen: set[tuple[str, str, str]] = set()
    for u, v, edata in graph.edges(data=True):
        if u in nodes and v in nodes:
            key = (u, v, edata["field"])
            if key not in seen:
                seen.add(key)
                edges.append((
                    u, v,
                    edata["rel_type"],
                    edata["field"],
                    edata.get("self_ref", False),
                ))

    return objects_map, edges
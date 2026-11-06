"""Read-only query and review interface for schema-v1 traceability graphs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "doorstop-edit-migration-traceability/1"
PATH_TYPES = ("Requirement", "Capability", "Source", "AutomatedTest", "BeadsIssue")
IMPACT_RELATIONS = {"impacts", "derivedFrom", "implementedBy", "verifiedBy", "trackedBy"}
FRESHNESS = {"current", "stale", "unknown"}
VERIFY = {"verified", "failed", "notRun", "unverified"}
COVERAGE = {"covered", "uncovered", "untestable", "notAssessed"}
PROVENANCE_KINDS = {
    "doorstop",
    "capability-register",
    "repository",
    "test-run",
    "manual-review",
    "beads",
    "evidence-artifact",
}


def load_graph(path: Path) -> dict[str, Any]:
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read graph: {exc}") from exc
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    schema = graph.get("schemaId")
    if schema != SCHEMA:
        raise ValueError(f"unsupported schemaId: {schema!r}")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("graph nodes and edges must be arrays")
    ids: set[str] = set()
    edge_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not isinstance(node.get("type"), str):
            raise ValueError("malformed node")
        if node["id"] in ids:
            raise ValueError(f"duplicate node id: {node['id']}")
        ids.add(node["id"])
        _validate_claim(node, "node")
    for edge in edges:
        if not isinstance(edge, dict) or not all(
            isinstance(edge.get(k), str) for k in ("id", "type", "sourceId", "targetId")
        ):
            raise ValueError("malformed edge")
        if edge["id"] in edge_ids:
            raise ValueError(f"duplicate edge id: {edge['id']}")
        edge_ids.add(edge["id"])
        if edge["sourceId"] not in ids or edge["targetId"] not in ids:
            raise ValueError(f"unresolved edge endpoint: {edge['id']}")
        if edge["sourceId"] == edge["targetId"]:
            raise ValueError(f"malformed edge endpoints: {edge['id']}")
        _validate_claim(edge, "edge")
    repository = graph.get("repository")
    if (
        not isinstance(repository, dict)
        or not isinstance(repository.get("id"), str)
        or not isinstance(repository.get("revision"), str)
    ):
        raise ValueError("malformed repository snapshot")
    if not isinstance(graph.get("generatedAt"), str) or not graph["generatedAt"]:
        raise ValueError("malformed generatedAt")
    return graph


def _validate_claim(item: dict[str, Any], kind: str) -> None:
    ident = item.get("id", "<unknown>")
    if item.get("freshness") not in FRESHNESS:
        raise ValueError(f"malformed {kind} freshness: {ident}")
    if "verificationStatus" in item and item["verificationStatus"] not in VERIFY:
        raise ValueError(f"malformed {kind} verificationStatus: {ident}")
    if "coverageStatus" in item and item["coverageStatus"] not in COVERAGE:
        raise ValueError(f"malformed {kind} coverageStatus: {ident}")
    provenance = item.get("provenance")
    required = ("sourceKind", "sourceLocator", "observedAt", "method", "repositoryRevision")
    if not isinstance(provenance, dict) or any(
        not isinstance(provenance.get(key), str) or not provenance[key] for key in required
    ):
        raise ValueError(f"malformed {kind} provenance: {ident}")
    if provenance["sourceKind"] not in PROVENANCE_KINDS or provenance["method"] not in {
        "automated",
        "manual",
        "derived",
    }:
        raise ValueError(f"malformed {kind} provenance: {ident}")


def _index(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    return ({n["id"]: n for n in graph["nodes"]}, sorted(graph["edges"], key=lambda e: e["id"]))


def _citation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "type",
            "sourceId",
            "targetId",
            "freshness",
            "provenance",
            "verificationStatus",
            "coverageStatus",
        )
        if key in item
    }


def query(graph: dict[str, Any], node_id: str, view: str = "forward") -> dict[str, Any]:
    """Run forward path, reverse impact, or single-node review without inference."""
    if graph.get("schemaId") != SCHEMA:
        raise ValueError(f"unsupported schemaId: {graph.get('schemaId')!r}")
    nodes, edges = _index(graph)
    if node_id not in nodes:
        raise ValueError(f"unknown node id: {node_id}")
    if view not in ("forward", "impact", "review"):
        raise ValueError(f"unknown view: {view}")
    if view == "review":
        node = nodes[node_id]
        related = [e for e in edges if e["sourceId"] == node_id or e["targetId"] == node_id]
        gaps = []
        if node.get("type") in ("Requirement", "Capability") and node.get("coverageStatus") in (
            None,
            "uncovered",
            "untestable",
            "notAssessed",
        ):
            gaps.append({"nodeId": node_id, "coverageStatus": node.get("coverageStatus", "unknown")})
        return {
            "view": view,
            "repository": graph.get("repository"),
            "generatedAt": graph.get("generatedAt"),
            "node": _citation(node),
            "gaps": gaps,
            "edges": [_citation(e) for e in related],
        }
    if view == "impact":
        # Only declared product-impact relationships participate. Evidence links are not product impact.
        adjacency: dict[str, list[dict[str, Any]]] = {ident: [] for ident in nodes}
        for edge in edges:
            if edge["type"] not in IMPACT_RELATIONS:
                continue
            adjacency[edge["sourceId"]].append(edge)
            adjacency[edge["targetId"]].append(edge)
        seen_nodes = {node_id}
        seen_edges: dict[str, dict[str, Any]] = {}
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            for edge in adjacency[current]:
                seen_edges[edge["id"]] = edge
                neighbor = edge["targetId"] if edge["sourceId"] == current else edge["sourceId"]
                if neighbor not in seen_nodes:
                    seen_nodes.add(neighbor)
                    queue.append(neighbor)
        return {
            "view": view,
            "repository": graph.get("repository"),
            "generatedAt": graph.get("generatedAt"),
            "startId": node_id,
            "nodes": [_citation(nodes[i]) for i in sorted(seen_nodes) if i != node_id],
            "edges": [_citation(seen_edges[i]) for i in sorted(seen_edges)],
        }

    paths: list[dict[str, Any]] = []
    if nodes[node_id].get("type") == PATH_TYPES[0]:

        def walk(
            current: str, depth: int, used: frozenset[str], path_nodes: list[str], path_edges: list[dict[str, Any]]
        ) -> None:
            if depth == len(PATH_TYPES) - 1:
                paths.append(
                    {"nodes": [_citation(nodes[i]) for i in path_nodes], "edges": [_citation(e) for e in path_edges]}
                )
                return
            wanted = PATH_TYPES[depth + 1]
            for edge in edges:
                if edge["id"] in used:
                    continue
                if edge["sourceId"] == current and edge["targetId"] in nodes:
                    nxt = edge["targetId"]
                elif edge["targetId"] == current:
                    nxt = edge["sourceId"]
                else:
                    continue
                if nodes[nxt].get("type") == wanted:
                    walk(nxt, depth + 1, used | {edge["id"]}, path_nodes + [nxt], path_edges + [edge])

        walk(node_id, 0, frozenset(), [node_id], [])
    gaps = []
    if not paths:
        gaps.append({"nodeId": node_id, "missingPath": list(PATH_TYPES)})
    return {
        "view": view,
        "repository": graph.get("repository"),
        "generatedAt": graph.get("generatedAt"),
        "startId": node_id,
        "paths": paths,
        "gaps": gaps,
    }


def render_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Refresh with .8.2: generate the graph, validate it, then rerun this query. "
            "Results describe only that graph snapshot; stale line hints must be revalidated."
        ),
    )
    parser.add_argument("graph", type=Path)
    parser.add_argument("node_id", help="stable graph node ID")
    parser.add_argument("--view", choices=("forward", "impact", "review"), default="forward")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    try:
        result = query(load_graph(args.graph), args.node_id, args.view)
    except ValueError as exc:
        print(f"traceability-query: {exc}", file=sys.stderr)
        return 2
    output = (
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.format == "json"
        else render_text(result)
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

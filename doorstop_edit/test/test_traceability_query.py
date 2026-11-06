import json
from pathlib import Path
from typing import Any

import pytest

from tools.traceability_query import load_graph, query

SCHEMA = "doorstop-edit-migration-traceability/1"


def node(ident: str, typ: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": ident,
        "type": typ,
        "provenance": {
            "sourceKind": "repository",
            "sourceLocator": ident,
            "repositoryRevision": "unknown",
            "observedAt": "now",
            "method": "automated",
        },
        "freshness": "unknown",
        **extra,
    }


def edge(typ: str, source: str, target: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"rel:{typ}:{source}->{target}",
        "type": typ,
        "sourceId": source,
        "targetId": target,
        "freshness": "current",
        "provenance": {
            "sourceKind": "repository",
            "sourceLocator": "fixture",
            "repositoryRevision": "abc",
            "observedAt": "now",
            "method": "automated",
        },
        **extra,
    }


def graph() -> dict[str, Any]:
    ids = [
        ("req:R", "Requirement"),
        ("cap:CAP-C", "Capability"),
        ("source:x.py", "Source"),
        ("test:t.py::test_x", "AutomatedTest"),
        ("beads:p-1", "BeadsIssue"),
    ]
    ns = [node(i, t, **({"coverageStatus": "uncovered"} if t == "Requirement" else {})) for i, t in ids]
    es = [
        edge("derivedFrom", "cap:CAP-C", "req:R"),
        edge("implementedBy", "cap:CAP-C", "source:x.py"),
        edge("impacts", "source:x.py", "test:t.py::test_x"),
        edge("trackedBy", "test:t.py::test_x", "beads:p-1"),
    ]
    return {
        "schemaId": SCHEMA,
        "repository": {"id": "repo", "revision": "abc"},
        "generatedAt": "now",
        "nodes": ns,
        "edges": es,
    }


def test_forward_path_citations_and_order_are_deterministic() -> None:
    g = graph()
    result = query(g, "req:R")
    assert [n["id"] for n in result["paths"][0]["nodes"]] == [
        "req:R",
        "cap:CAP-C",
        "source:x.py",
        "test:t.py::test_x",
        "beads:p-1",
    ]
    assert result == query({**g, "nodes": list(reversed(g["nodes"])), "edges": list(reversed(g["edges"]))}, "req:R")
    assert all(e["provenance"] and e["freshness"] for e in result["paths"][0]["edges"])


def test_reverse_impact_uses_inverse_edges_without_duplicates() -> None:
    result = query(graph(), "beads:p-1", "impact")
    assert {n["id"] for n in result["nodes"]} == {"req:R", "cap:CAP-C", "source:x.py", "test:t.py::test_x"}
    assert len({e["id"] for e in result["edges"]}) == 4
    assert result["repository"]["revision"] == "abc"
    assert result["generatedAt"] == "now"


def test_review_reports_gap_and_unknown_stale_metadata() -> None:
    g = graph()
    g["nodes"][0]["freshness"] = "stale"
    result = query(g, "req:R", "review")
    assert result["gaps"] == [{"nodeId": "req:R", "coverageStatus": "uncovered"}]
    assert result["repository"] == {"id": "repo", "revision": "abc"}
    assert result["node"]["freshness"] == "stale"
    assert result["edges"][0]["provenance"]


def test_no_path_is_not_inferred() -> None:
    g = graph()
    g["edges"] = []
    assert query(g, "req:R")["paths"] == []
    assert query(g, "req:R")["gaps"]


def test_unknown_major_and_unresolved_graph_rejected(tmp_path: Path) -> None:
    g = graph()
    g["schemaId"] = "doorstop-edit-migration-traceability/2"
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(g))
    with pytest.raises(ValueError, match="unsupported schemaId"):
        load_graph(path)
    g = graph()
    g["edges"][0]["targetId"] = "missing"
    path.write_text(json.dumps(g))
    with pytest.raises(ValueError, match="unresolved edge endpoint"):
        load_graph(path)


def test_impact_ignores_evidence_and_other_nonimpact_relations() -> None:
    g = graph()
    g["nodes"].append(node("evidence:run.json#run", "Evidence"))
    g["edges"].append(edge("evidencedBy", "test:t.py::test_x", "evidence:run.json#run"))
    result = query(g, "beads:p-1", "impact")
    assert "evidence:run.json#run" not in {n["id"] for n in result["nodes"]}
    assert all(e["type"] != "evidencedBy" for e in result["edges"])


def test_malformed_duplicate_edge_and_provenance_are_rejected(tmp_path: Path) -> None:
    g = graph()
    g["edges"].append(dict(g["edges"][0]))
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(g))
    with pytest.raises(ValueError, match="duplicate edge id"):
        load_graph(path)
    g = graph()
    g["nodes"][0]["provenance"] = {}
    path.write_text(json.dumps(g))
    with pytest.raises(ValueError, match="malformed node provenance"):
        load_graph(path)

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.traceability import build, status_report, validate


def test_build_is_stable_and_keeps_gaps(tmp_path: Path) -> None:
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements/REQ-001.yml").write_text("text: |\n  Example\nsource: ../docs/a.md#x\nevidence: []\n")
    graph = build(tmp_path, "2026-01-01T00:00:00+00:00")
    assert graph == build(tmp_path, "2026-01-01T00:00:00+00:00")
    req = next(n for n in graph["nodes"] if n["id"] == "req:REQ-001")
    assert req["coverageStatus"] == "uncovered"
    assert "full coverage" not in json.dumps(graph)
    assert validate(graph) == []


def test_validator_rejects_broken_edge_and_bad_type() -> None:
    graph = {
        "schemaId": "doorstop-edit-migration-traceability/1",
        "nodes": [
            {
                "id": "req:R",
                "type": "Requirement",
                "provenance": {
                    "sourceKind": "doorstop",
                    "sourceLocator": "R",
                    "observedAt": "now",
                    "method": "automated",
                    "repositoryRevision": "a",
                },
            },
            {
                "id": "cap:CAP-C",
                "type": "Capability",
                "provenance": {
                    "sourceKind": "capability-register",
                    "sourceLocator": "C",
                    "observedAt": "now",
                    "method": "automated",
                    "repositoryRevision": "a",
                },
            },
        ],
        "edges": [
            {
                "id": "rel:implementedBy:req:R->cap:CAP-C",
                "type": "implementedBy",
                "sourceId": "req:R",
                "targetId": "cap:CAP-C",
                "provenance": {"sourceLocator": "x"},
            }
        ],
    }
    errors = validate(graph)
    assert any("invalid edge type/endpoints" in error for error in errors)
    edge = graph["edges"][0]
    assert isinstance(edge, dict)
    edge["targetId"] = "missing"
    assert any("broken edge endpoint" in error for error in validate(graph))


def test_capability_source_and_test_paths_are_explicit(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "doorstop_edit/test").mkdir(parents=True)
    (tmp_path / "doorstop_edit/main.py").write_text("pass\n")
    (tmp_path / "doorstop_edit/test/test_main.py").write_text("def test_start(): pass\n")
    (tmp_path / "docs/qml-frontend-analysis.md").write_text(
        "| CAP-START | Start | `main.py:1-2` | `doorstop_edit/test/test_main.py::test_start` |\n"
    )
    graph = build(tmp_path, "2026-01-01T00:00:00+00:00")
    ids = {node["id"] for node in graph["nodes"]}
    assert "source:main.py" in ids
    assert "test:doorstop_edit/test/test_main.py::test_start" in ids
    assert any(edge["type"] == "implementedBy" for edge in graph["edges"])
    assert any(edge["type"] == "verifiedBy" and edge["sourceId"] == "cap:CAP-START" for edge in graph["edges"])
    assert all(node["freshness"] == "unknown" for node in graph["nodes"])


def test_validator_rejects_bad_ids_statuses_and_locators(tmp_path: Path) -> None:
    graph = build(tmp_path, "2026-01-01T00:00:00+00:00")
    graph["nodes"] = [
        {
            "id": "bad",
            "type": "Capability",
            "properties": {},
            "provenance": {
                "sourceKind": "repository",
                "sourceLocator": "../secret.py",
                "observedAt": "now",
                "method": "automated",
                "repositoryRevision": "unknown",
            },
            "freshness": "fresh",
            "verificationStatus": "passed",
            "coverageStatus": "complete",
        }
    ]
    errors = validate(graph, tmp_path)
    assert any("invalid node id" in error for error in errors)


def test_validator_handles_malformed_graph_objects() -> None:
    assert validate(None) == ["graph must be an object"]
    assert any(
        "node 0 must be an object" in error
        for error in validate({"schemaId": "doorstop-edit-migration-traceability/1", "nodes": [None], "edges": [None]})
    )


def test_status_report_lists_gaps_and_unknown_without_failure(tmp_path: Path) -> None:
    graph = build(tmp_path, "2026-01-01T00:00:00+00:00")
    graph["nodes"].append(
        {
            "id": "req:REQ-002",
            "type": "Requirement",
            "properties": {},
            "provenance": {
                "sourceKind": "doorstop",
                "sourceLocator": "REQ-002",
                "observedAt": graph["generatedAt"],
                "method": "automated",
                "repositoryRevision": "unknown",
            },
            "freshness": "unknown",
            "verificationStatus": "unverified",
            "coverageStatus": "untestable",
        }
    )
    output = status_report(graph, tmp_path)
    assert output[0] == "Coverage gaps (not compliance failures):"
    assert "  req:REQ-002: untestable" in output
    assert "Unknown nodes/edges:" in output


def test_validator_rejects_unhashable_fields_and_edge_provenance() -> None:
    graph = {
        "schemaId": "doorstop-edit-migration-traceability/1",
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "repository": {"id": "doorstop-edit", "revision": "unknown"},
        "nodes": [
            {
                "id": "req:R",
                "type": "Requirement",
                "properties": {},
                "freshness": [],
                "verificationStatus": [],
                "coverageStatus": [],
                "provenance": {
                    "sourceKind": [],
                    "sourceLocator": "R",
                    "observedAt": "now",
                    "method": "automated",
                    "repositoryRevision": "unknown",
                },
            }
        ],
        "edges": [
            {
                "id": [],
                "type": [],
                "sourceId": [],
                "targetId": {},
                "freshness": [],
                "provenance": {"sourceLocator": "x"},
            }
        ],
    }
    assert validate(graph)


def test_status_report_marks_current_claim_stale_on_later_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep the test repository nested: pytest may set --basetemp to the checkout.
    repository = tmp_path / "repository"
    repository.mkdir()
    parent = Path(__file__).resolve().parents[2]
    clean_env = os.environ.copy()
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_PREFIX",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        clean_env.pop(key, None)
    parent_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=parent,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Simulate a pre-push hook environment that redirects ordinary Git commands.
    monkeypatch.setenv("GIT_DIR", str(parent / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(parent))
    git_env = clean_env
    graph = {
        "repository": {"revision": "0" * 40},
        "nodes": [
            {
                "id": "req:R",
                "type": "Requirement",
                "freshness": "current",
                "provenance": {"repositoryRevision": "0" * 40},
            }
        ],
        "edges": [],
    }
    subprocess.run(["git", "init", "-q"], cwd=repository, env=git_env, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, env=git_env, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, env=git_env, check=True)
    (repository / "snapshot.txt").write_text("snapshot")
    subprocess.run(["git", "add", "snapshot.txt"], cwd=repository, env=git_env, check=True)
    subprocess.run(["git", "commit", "-qm", "snapshot"], cwd=repository, env=git_env, check=True)
    report = status_report(graph, repository)
    assert report[report.index("Stale nodes/edges:") + 1] == "  req:R"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=parent,
            env=clean_env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == parent_head
    )


def test_validator_requires_edge_provenance_fields() -> None:
    graph = {
        "schemaId": "doorstop-edit-migration-traceability/1",
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "repository": {"id": "doorstop-edit", "revision": "unknown"},
        "nodes": [
            {
                "id": "req:R",
                "type": "Requirement",
                "properties": {},
                "freshness": "unknown",
                "provenance": {
                    "sourceKind": "doorstop",
                    "sourceLocator": "R",
                    "observedAt": "now",
                    "method": "automated",
                    "repositoryRevision": "unknown",
                },
            },
            {
                "id": "beads:x",
                "type": "BeadsIssue",
                "properties": {},
                "freshness": "unknown",
                "provenance": {
                    "sourceKind": "beads",
                    "sourceLocator": "x",
                    "observedAt": "now",
                    "method": "automated",
                    "repositoryRevision": "unknown",
                },
            },
        ],
        "edges": [
            {
                "id": "rel:trackedBy:req:R->beads:x",
                "type": "trackedBy",
                "sourceId": "req:R",
                "targetId": "beads:x",
                "freshness": "unknown",
                "provenance": {"sourceLocator": "x"},
            }
        ],
    }
    assert any("edge provenance" in error for error in validate(graph))

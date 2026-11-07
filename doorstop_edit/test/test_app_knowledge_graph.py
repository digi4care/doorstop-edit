from pathlib import Path
from typing import Any, Iterator

from doorstop import DoorstopError

from doorstop_edit.app_knowledge_graph import GraphSnapshot, build_app_knowledge_graph
from doorstop_edit.doorstop_data import DoorstopData, ValidationFinding
from tools.gen_sample_tree import generate_tree


class UID:
    def __init__(self, value: str) -> None:
        self.value = value


class Link:
    def __init__(self, value: str, stamp: str = "stamp") -> None:
        self.value = value
        self.stamp = stamp


class Item:
    def __init__(self, uid: str, *, links: tuple[Link, ...] = (), stamp: str = "stamp", reviewed: bool = True) -> None:
        self.uid = UID(uid)
        self.path = Path("/project") / uid.split("-")[0] / f"{uid}.req"
        self.links = links
        self._stamp = stamp
        self.reviewed = reviewed
        self.level = 1
        self.header = uid
        self.text = "text"
        self.active = True
        self.normative = True
        self.derived = False

    def stamp(self) -> str:
        return self._stamp


class Document:
    def __init__(self, prefix: str, items: list[Item], parent: object = None) -> None:
        self.prefix = prefix
        self.path = Path("/project") / prefix
        self.parent = parent
        self.items = items

    def __iter__(self) -> Iterator[Item]:
        return iter(self.items)


class Data:
    root = Path("/project")

    def __init__(self, documents: dict[str, Document]) -> None:
        self.documents = documents

    def get_documents(self) -> dict[str, Document]:
        return self.documents

    def iter_items(self, document: Document) -> Iterator[Item]:
        yield from document


def graph(items: list[Item], **kwargs: Any) -> GraphSnapshot:
    doc = Document("REQ", items)
    return build_app_knowledge_graph(Data({"REQ": doc}), **kwargs)


def test_ids_provenance_and_project_root_scope() -> None:
    first = graph([Item("REQ-1")], content_revision=3, graph_generation=4)
    second = graph([Item("REQ-1")])
    assert first.project_id == second.project_id
    assert {n.id for n in first.nodes} >= {"project:/project", "document:REQ", "item:REQ-1"}
    item = next(n for n in first.nodes if n.id == "item:REQ-1")
    assert item.provenance.source_path == "REQ/REQ-1.req"
    assert (item.provenance.content_revision, item.provenance.graph_generation) == (3, 4)
    assert "doorstop" not in repr(first)
    other = Data({"REQ": Document("REQ", [Item("REQ-1")])})
    other.root = Path("/elsewhere")
    assert build_app_knowledge_graph(other).project_id != first.project_id


def test_document_and_link_direction() -> None:
    a = Item("REQ-1", links=(Link("REQ-2"),))
    b = Item("REQ-2")
    snapshot = graph([a, b])
    edges = {(e.relation_type, e.source_id, e.target_id) for e in snapshot.edges}
    assert ("containsDocument", "project:/project", "document:REQ") in edges
    assert ("containsItem", "document:REQ", "item:REQ-1") in edges
    assert ("linksTo", "item:REQ-1", "item:REQ-2") in edges


def test_incoming_transitive_impact_is_cycle_safe() -> None:
    a = Item("REQ-1", links=(Link("REQ-2"),))
    b = Item("REQ-2", links=(Link("REQ-3"),))
    c = Item("REQ-3", links=(Link("REQ-1"),))
    snapshot = graph([a, b, c])
    assert set(snapshot.impacted_by("item:REQ-1")) == {"item:REQ-2", "item:REQ-3"}
    assert snapshot.impacted_by("item:REQ-1", transitive=False) == ("item:REQ-3",)


def test_unresolved_reviewed_and_suspect_links() -> None:
    snapshot = graph(
        [Item("REQ-1", links=(Link("REQ-2", "old"), Link("MISSING")), reviewed=False), Item("REQ-2", stamp="new")]
    )
    statuses = {e.target_id: e.status for e in snapshot.edges if e.relation_type == "linksTo"}
    assert statuses == {"item:REQ-2": "suspect", "unresolved-item:MISSING": "unresolved"}
    node = next(n for n in snapshot.nodes if n.id == "item:REQ-1")
    assert dict(node.data)["reviewed"] == "needsReview"
    assert any(n.id == "unresolved-item:MISSING" for n in snapshot.nodes)
    serialized_link = next(
        e for e in snapshot.to_primitives()["edges"] if e["type"] == "linksTo" and e["targetId"] == "item:REQ-2"
    )
    assert serialized_link["provenance"]["storedLinkStamp"] == "old"
    assert serialized_link["provenance"]["currentTargetStamp"] == "new"


def test_load_errors_have_no_stale_fields() -> None:
    snapshot = graph([Item("REQ-1")], load_errors={"REQ-1": "bad item"})
    item = next(n for n in snapshot.nodes if n.id == "item:REQ-1")
    assert dict(item.data) == {
        "documentId": "document:REQ",
        "error": "bad item",
        "loadState": "error",
        "reviewed": "unknown",
        "uid": "REQ-1",
    }


def test_missing_item_property_emits_error_state_item() -> None:
    class MissingHeaderItem(Item):
        @property
        def header(self) -> str:
            raise AttributeError("header unavailable")

        @header.setter
        def header(self, value: str) -> None:
            pass

    snapshot = graph([MissingHeaderItem("REQ-1")])
    item = next(node for node in snapshot.nodes if node.id == "item:REQ-1")
    assert dict(item.data) == {
        "documentId": "document:REQ",
        "error": "header unavailable",
        "loadState": "error",
        "reviewed": "unknown",
        "uid": "REQ-1",
    }


def test_validation_current_stale_and_project_association() -> None:
    findings = [ValidationFinding("error", "broken", "REQ-1"), ValidationFinding("warning", "whole project")]
    current = graph(
        [Item("REQ-1")],
        content_revision=5,
        validation_revision=5,
        validation_project_id="project:/project",
        validation_state="succeeded",
        validation_run_id="run",
        validation_findings=findings,
    )
    associated = {e.target_id for e in current.edges if e.relation_type == "reportedFor"}
    assert associated == {"item:REQ-1", "project:/project"}
    assert {dict(n.data)["state"] for n in current.nodes if n.node_type == "ValidationFinding"} == {"current"}
    stale = graph(
        [Item("REQ-1")],
        content_revision=6,
        validation_revision=5,
        validation_project_id="project:/project",
        validation_state="succeeded",
        validation_findings=findings,
    )
    assert {dict(n.data)["state"] for n in stale.nodes if n.node_type == "ValidationFinding"} == {"stale"}
    assert stale.graph_generation == 0 and stale.content_revision == 6
    different_project = graph(
        [Item("REQ-1")],
        content_revision=5,
        validation_revision=5,
        validation_state="succeeded",
        validation_project_id="project:/other",
        validation_findings=findings,
    )
    assert {dict(n.data)["state"] for n in different_project.nodes if n.node_type == "ValidationFinding"} == {"stale"}
    missing_origin = graph(
        [Item("REQ-1")],
        content_revision=5,
        validation_revision=5,
        validation_state="succeeded",
        validation_findings=findings,
    )
    assert missing_origin.validation_run.project_id is None
    assert {dict(n.data)["state"] for n in missing_origin.nodes if n.node_type == "ValidationFinding"} == {"stale"}
    missing_revision = graph(
        [Item("REQ-1")],
        content_revision=5,
        validation_project_id="project:/project",
        validation_state="succeeded",
        validation_findings=findings,
    )
    assert missing_revision.validation_run.input_content_revision is None
    assert {dict(n.data)["state"] for n in missing_revision.nodes if n.node_type == "ValidationFinding"} == {"stale"}


def test_parent_document_direction_and_primitive_serializer() -> None:
    parent = Document("TOP", [])
    child = Document("SUB", [], "TOP")
    snapshot = build_app_knowledge_graph(Data({"TOP": parent, "SUB": child}))
    edge = next(e for e in snapshot.edges if e.relation_type == "childDocumentOf")
    assert (edge.source_id, edge.target_id) == ("document:SUB", "document:TOP")
    primitive = snapshot.to_primitives()
    assert primitive["projectId"] == "project:/project"
    child_primitive = next(n for n in primitive["nodes"] if n["id"] == "document:SUB")
    assert child_primitive["provenance"] == {
        "sourcePath": "SUB",
        "sourceKind": "document-config",
        "sourceKey": "SUB",
        "event": "initial-load",
        "contentRevision": 0,
        "graphGeneration": 0,
        "observedAt": snapshot.nodes[0].provenance.observed_at,
        "storedLinkStamp": None,
        "currentTargetStamp": None,
    }
    edge_primitive = next(e for e in primitive["edges"] if e["type"] == "childDocumentOf")
    assert edge_primitive["provenance"]["sourceKey"] == "SUB"


def test_primitive_serializer_includes_finding_and_validation_provenance() -> None:
    snapshot = graph(
        [Item("REQ-1")],
        content_revision=7,
        graph_generation=9,
        observed_at="2024-01-01T00:00:00+00:00",
        validation_run_id="run-2",
        validation_project_id="project:/project",
        validation_revision=7,
        validation_state="succeeded",
        validation_findings=[ValidationFinding("error", "broken", "REQ-1")],
    )
    primitive = snapshot.to_primitives()
    finding = next(n for n in primitive["nodes"] if n["type"] == "ValidationFinding")
    assert finding["provenance"] == {
        "sourcePath": None,
        "sourceKind": "validation-result",
        "sourceKey": "run-2:REQ-1",
        "event": "initial-load",
        "contentRevision": 7,
        "graphGeneration": 9,
        "observedAt": "2024-01-01T00:00:00+00:00",
        "storedLinkStamp": None,
        "currentTargetStamp": None,
    }
    relation = next(e for e in primitive["edges"] if e["type"] == "reportedFor")
    assert relation["provenance"] == finding["provenance"]
    assert primitive["validationRun"] == {
        "runId": "run-2",
        "projectId": "project:/project",
        "inputContentRevision": 7,
        "state": "succeeded",
        "startedAt": None,
        "completedAt": None,
        "error": None,
    }


def test_real_doorstop_tree_parent_links_and_unloaded_target(doorstop_data: DoorstopData) -> None:
    snapshot = build_app_knowledge_graph(doorstop_data)
    parent_edges = [edge for edge in snapshot.edges if edge.relation_type == "childDocumentOf"]
    assert any(edge.source_id == "document:REQ-B" and edge.target_id == "document:REQ-A" for edge in parent_edges)

    source = doorstop_data.find_item("REQ-B-002")
    assert source is not None
    target_uid = "REQ-A-001"
    assert any(str(link.value) == target_uid for link in source.links)
    edge = next(
        edge
        for edge in snapshot.edges
        if edge.relation_type == "linksTo"
        and edge.source_id == "item:REQ-B-002"
        and edge.target_id == f"item:{target_uid}"
    )
    assert edge.status in {"ok", "suspect"}

    failed = build_app_knowledge_graph(doorstop_data, load_errors={target_uid: "load failed"})
    failed_target = next(node for node in failed.nodes if node.id == f"item:{target_uid}")
    assert dict(failed_target.data) == {
        "documentId": "document:REQ-A",
        "error": "load failed",
        "loadState": "error",
        "reviewed": "unknown",
        "uid": target_uid,
    }
    failed_edge = next(
        edge
        for edge in failed.edges
        if edge.relation_type == "linksTo"
        and edge.source_id == "item:REQ-B-002"
        and edge.target_id == f"item:{target_uid}"
    )
    assert failed_edge.status == "unknown"


class BrokenStampItem(Item):
    def stamp(self) -> str:
        raise DoorstopError("stamp unavailable")


def test_stamp_read_failure_is_unknown_and_comparison_is_provenanced() -> None:
    snapshot = graph(
        [Item("REQ-1", links=(Link("REQ-2", "saved-stamp"),)), BrokenStampItem("REQ-2")],
        observed_at="2024-01-01T00:00:00+00:00",
    )
    edge = next(edge for edge in snapshot.edges if edge.relation_type == "linksTo")
    assert edge.status == "unknown"
    serialized = snapshot.to_primitives()
    primitive_edge = next(edge for edge in serialized["edges"] if edge["type"] == "linksTo")
    assert primitive_edge["provenance"]["storedLinkStamp"] == "saved-stamp"
    assert primitive_edge["provenance"]["currentTargetStamp"] is None
    assert primitive_edge["provenance"]["observedAt"] == "2024-01-01T00:00:00+00:00"


def test_failed_validation_run_has_error_and_stale_findings() -> None:
    snapshot = graph(
        [Item("REQ-1")],
        validation_run_id="failed",
        validation_state="failed",
        validation_started_at="2024-01-01T00:00:00+00:00",
        validation_completed_at="2024-01-01T00:00:01+00:00",
        validation_error="worker exited",
        validation_findings=[ValidationFinding("error", "old finding", "REQ-1")],
    )
    primitives = snapshot.to_primitives()
    assert primitives["validationRun"] == {
        "runId": "failed",
        "projectId": None,
        "inputContentRevision": None,
        "state": "failed",
        "startedAt": "2024-01-01T00:00:00+00:00",
        "completedAt": "2024-01-01T00:00:01+00:00",
        "error": "worker exited",
    }
    finding = next(node for node in primitives["nodes"] if node["type"] == "ValidationFinding")
    assert finding["state"] == "stale"


def test_doorstop_data_load_error_registry_flows_into_graph(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    generate_tree(root, 2, 4)
    target_uid = "REQ-A-001"
    target_path = root / "REQ-A" / f"{target_uid}.yml"
    original = target_path.read_text(encoding="utf-8")
    target_path.write_text("not: [valid", encoding="utf-8")

    data = DoorstopData(None, root)
    data.rebuild(False)
    errors = data.item_load_errors()
    assert target_uid in errors
    errors.clear()
    assert target_uid in data.item_load_errors()  # accessor returns an independent copy

    failed = build_app_knowledge_graph(data)
    target = next(node for node in failed.nodes if node.id == f"item:{target_uid}")
    assert dict(target.data) == {
        "documentId": "document:REQ-A",
        "error": data.item_load_errors()[target_uid],
        "loadState": "error",
        "reviewed": "unknown",
        "uid": target_uid,
    }
    edge = next(
        edge
        for edge in failed.edges
        if edge.relation_type == "linksTo"
        and edge.source_id == "item:REQ-B-002"
        and edge.target_id == f"item:{target_uid}"
    )
    assert edge.status == "unknown"

    target_path.write_text(original, encoding="utf-8")
    data.rebuild(False)
    assert target_uid not in data.item_load_errors()
    recovered = build_app_knowledge_graph(data)
    recovered_target = next(node for node in recovered.nodes if node.id == f"item:{target_uid}")
    assert dict(recovered_target.data)["loadState"] == "loaded"
    assert "header" in dict(recovered_target.data)
    recovered_edge = next(
        edge
        for edge in recovered.edges
        if edge.relation_type == "linksTo"
        and edge.source_id == "item:REQ-B-002"
        and edge.target_id == f"item:{target_uid}"
    )
    assert recovered_edge.status in {"ok", "suspect"}

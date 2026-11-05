"""Immutable, value-only snapshots of the open Doorstop project."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import doorstop

from doorstop_edit.doorstop_data import ValidationFinding

LoadState = Literal["loaded", "error"]
_MISSING = object()
RunState = Literal["notRun", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class Provenance:
    source_path: str | None
    source_kind: str
    source_key: str
    event: str
    content_revision: int
    graph_generation: int
    observed_at: str
    stored_link_stamp: str | int | bool | None = None
    current_target_stamp: str | int | bool | None = None


@dataclass(frozen=True)
class GraphNode:
    id: str
    node_type: str
    provenance: Provenance
    data: tuple[tuple[str, str | int | bool | None], ...] = ()


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source_id: str
    target_id: str
    relation_type: str
    status: str
    provenance: Provenance


@dataclass(frozen=True)
class ValidationRun:
    run_id: str
    project_id: str | None
    input_content_revision: int | None
    state: RunState
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class GraphSnapshot:
    project_id: str
    content_revision: int
    graph_generation: int
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    validation_run: ValidationRun

    def impacted_by(self, item_id: str, transitive: bool = True) -> tuple[str, ...]:
        """Return incoming-link item IDs, without repeating nodes in cycles."""
        incoming: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge.relation_type == "linksTo" and edge.status != "unresolved":
                incoming.setdefault(edge.target_id, []).append(edge.source_id)
        seen = {item_id}
        pending = deque(incoming.get(item_id, ()))
        result: list[str] = []
        while pending:
            source = pending.popleft()
            if source in seen:
                continue
            seen.add(source)
            result.append(source)
            if transitive:
                pending.extend(incoming.get(source, ()))
        return tuple(result)

    def to_primitives(self) -> dict[str, Any]:
        """Serialize the snapshot to simple QML-friendly primitive values."""
        return {
            "projectId": self.project_id,
            "contentRevision": self.content_revision,
            "graphGeneration": self.graph_generation,
            "nodes": [
                {"id": n.id, "type": n.node_type, **dict(n.data), "provenance": _provenance_primitives(n.provenance)}
                for n in self.nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "sourceId": e.source_id,
                    "targetId": e.target_id,
                    "type": e.relation_type,
                    "status": e.status,
                    "provenance": _provenance_primitives(e.provenance),
                }
                for e in self.edges
            ],
            "validationRun": {
                "runId": self.validation_run.run_id,
                "projectId": self.validation_run.project_id,
                "inputContentRevision": self.validation_run.input_content_revision,
                "state": self.validation_run.state,
                "startedAt": self.validation_run.started_at,
                "completedAt": self.validation_run.completed_at,
                "error": self.validation_run.error,
            },
        }


def _provenance_primitives(provenance: Provenance) -> dict[str, str | int | None]:
    return {
        "sourcePath": provenance.source_path,
        "sourceKind": provenance.source_kind,
        "sourceKey": provenance.source_key,
        "event": provenance.event,
        "contentRevision": provenance.content_revision,
        "graphGeneration": provenance.graph_generation,
        "observedAt": provenance.observed_at,
        "storedLinkStamp": provenance.stored_link_stamp,
        "currentTargetStamp": provenance.current_target_stamp,
    }


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except (doorstop.DoorstopError, AttributeError, TypeError, ValueError, OSError):
        return default


def _relative(root: Path, value: Any) -> str | None:
    if value is None:
        return None
    try:
        return Path(value).resolve().relative_to(root).as_posix()
    except (ValueError, OSError, TypeError):
        return None


def _primitive(value: Any) -> str | int | bool | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def build_app_knowledge_graph(
    data: Any,
    *,
    content_revision: int = 0,
    graph_generation: int = 0,
    load_errors: Mapping[str, str] | None = None,
    validation_findings: Iterable[ValidationFinding] | None = None,
    validation_run_id: str = "none",
    validation_revision: int | None = None,
    validation_state: RunState = "notRun",
    validation_project_id: str | None = None,
    validation_started_at: str | None = None,
    validation_completed_at: str | None = None,
    validation_error: str | None = None,
    observed_at: str | None = None,
    event: str = "initial-load",
) -> GraphSnapshot:
    """Project current DoorstopData into immutable values; never retain its objects."""
    root = Path(data.root).resolve()
    project_id = f"project:{root}"
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    observed = observed_at or datetime.now(timezone.utc).isoformat()

    def prov(
        path: str | None, kind: str, key: str, *, stored_stamp: Any = None, current_stamp: Any = None
    ) -> Provenance:
        return Provenance(
            path,
            kind,
            key,
            event,
            content_revision,
            graph_generation,
            observed,
            _primitive(stored_stamp),
            _primitive(current_stamp),
        )

    def add_node(identifier: str, kind: str, provenance: Provenance, **fields: Any) -> None:
        values = tuple(sorted((key, _primitive(value)) for key, value in fields.items()))
        nodes.append(GraphNode(identifier, kind, provenance, values))

    pp = prov(None, "derived", "project")
    add_node(project_id, "Project", pp, root=str(root))
    documents = data.get_documents()
    for prefix, document in documents.items():
        path = _relative(root, _attr(document, "path"))
        did = f"document:{prefix}"
        dp = prov(path, "document-config", str(prefix))
        try:
            count = sum(1 for _ in document)
        except doorstop.DoorstopError:
            count = 0
        add_node(did, "Document", dp, prefix=str(prefix), path=path, itemCount=count)
        edges.append(GraphEdge(f"containsDocument:{did}", project_id, did, "containsDocument", "ok", dp))
        parent = _attr(document, "parent")
        parent_prefix = parent if isinstance(parent, str) else _attr(parent, "prefix")
        if parent_prefix is not None and str(parent_prefix) in documents:
            parent_id = f"document:{parent_prefix}"
            edges.append(GraphEdge(f"childDocumentOf:{did}:{parent_id}", did, parent_id, "childDocumentOf", "ok", dp))

    error_accessor = getattr(data, "item_load_errors", None)
    errors = (error_accessor() if callable(error_accessor) else {}) if load_errors is None else load_errors
    records: dict[str, tuple[Any, str, str | None]] = {}
    for prefix, document in documents.items():
        try:
            items = data.iter_items(document)
            for item in items:
                uid_obj = _attr(item, "uid")
                uid = str(_attr(uid_obj, "value", uid_obj))
                records[uid] = (item, str(prefix), _relative(root, _attr(item, "path")))
        except doorstop.DoorstopError:
            continue

    for uid, (item, prefix, path) in records.items():
        iid = f"item:{uid}"
        ip = prov(path, "item-file", uid)
        if uid in errors:
            add_node(
                iid,
                "Item",
                ip,
                uid=uid,
                documentId=f"document:{prefix}",
                loadState="error",
                error=errors[uid],
                reviewed="unknown",
            )
        else:
            try:
                reviewed = bool(item.reviewed)
                add_node(
                    iid,
                    "Item",
                    ip,
                    uid=uid,
                    documentId=f"document:{prefix}",
                    level=item.level,
                    header=item.header,
                    text=str(item.text)[:500],
                    active=item.active,
                    normative=item.normative,
                    derived=item.derived,
                    reviewed="reviewed" if reviewed else "needsReview",
                    loadState="loaded",
                )
            except doorstop.DoorstopError as exc:
                add_node(
                    iid,
                    "Item",
                    ip,
                    uid=uid,
                    documentId=f"document:{prefix}",
                    loadState="error",
                    error=str(exc),
                    reviewed="unknown",
                )
        ep = prov(path, "derived", f"{uid}:containment")
        edges.append(GraphEdge(f"containsItem:{prefix}:{uid}", f"document:{prefix}", iid, "containsItem", "ok", ep))

    unresolved: set[str] = set()
    for uid, (item, _, path) in records.items():
        if uid in errors:
            continue
        source_id = f"item:{uid}"
        try:
            links = _attr(item, "links", ())
            for link in links:
                target_uid = str(_attr(link, "value", link))
                target = records.get(target_uid)
                stored = _MISSING
                actual = _MISSING
                if target is None:
                    target_id = f"unresolved-item:{target_uid}"
                    if target_uid not in unresolved:
                        unresolved.add(target_uid)
                        add_node(target_id, "UnresolvedItem", prov(None, "derived", target_uid), uid=target_uid)
                    status = "unresolved"
                else:
                    target_id = f"item:{target_uid}"
                    if target_uid not in errors:
                        try:
                            stored = getattr(link, "stamp")
                            stored = stored() if callable(stored) else stored
                            actual = getattr(target[0], "stamp")
                            actual = actual() if callable(actual) else actual
                            status = "ok" if stored == actual else "suspect"
                        except (doorstop.DoorstopError, AttributeError, TypeError, ValueError, OSError):
                            actual = _MISSING
                            status = "unknown"
                    else:
                        status = "unknown"
                ep = prov(
                    path,
                    "item-file",
                    f"{uid}:links:{target_uid}",
                    stored_stamp=None if stored is _MISSING else stored,
                    current_stamp=None if actual is _MISSING else actual,
                )
                edges.append(GraphEdge(f"link:{uid}:{target_uid}", source_id, target_id, "linksTo", status, ep))
        except doorstop.DoorstopError:
            continue

    run_revision = validation_revision
    run_project_id = validation_project_id
    run = ValidationRun(
        validation_run_id,
        run_project_id,
        run_revision,
        validation_state,
        validation_started_at,
        validation_completed_at,
        validation_error,
    )
    is_current = (
        run_project_id is not None
        and run_project_id == project_id
        and run_revision is not None
        and run_revision == content_revision
        and validation_state == "succeeded"
    )
    for ordinal, finding in enumerate(validation_findings or (), start=1):
        fid = f"finding:{validation_run_id}:{ordinal}"
        item_uid = finding.item_uid
        target_id = f"item:{item_uid}" if item_uid in records else project_id
        fp = prov(None, "validation-result", f"{validation_run_id}:{item_uid or 'project'}")
        add_node(
            fid,
            "ValidationFinding",
            fp,
            severity=finding.severity,
            message=finding.message,
            itemUid=item_uid,
            state="current" if is_current else "stale",
        )
        edges.append(GraphEdge(f"reportedFor:{fid}:{target_id}", fid, target_id, "reportedFor", "ok", fp))
    return GraphSnapshot(project_id, content_revision, graph_generation, tuple(nodes), tuple(edges), run)

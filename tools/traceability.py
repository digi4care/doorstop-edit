"""Deterministic traceability graph generator and validator (schema v1)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "doorstop-edit-migration-traceability/1"
_GIT_LOCAL_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _git_env() -> dict[str, str]:
    """Prevent inherited hook Git overrides from redirecting repository queries."""
    env = os.environ.copy()
    for key in _GIT_LOCAL_ENV:
        env.pop(key, None)
    return env


def rev(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True, env=_git_env()
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build(root: Path = ROOT, generated_at: str | None = None) -> dict[str, Any]:
    commit = rev(root)
    clean = False
    try:
        clean = not subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True, env=_git_env()
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    now = generated_at or datetime.now(timezone.utc).isoformat()
    nodes = []
    edges = []

    def fresh(path: str | None) -> str:
        if not clean or commit == "unknown" or not path:
            return "unknown"
        return "current" if (root / path).is_file() else "stale"

    def prov(kind: str, locator: str) -> dict[str, str]:
        return {
            "sourceKind": kind,
            "sourceLocator": locator,
            "observedAt": now,
            "method": "automated",
            "repositoryRevision": commit,
        }

    def add(
        ident: str,
        typ: str,
        props: dict[str, Any],
        kind: str,
        loc: str,
        coverage: str | None = None,
        freshness: str | None = None,
    ) -> None:
        n = {
            "id": ident,
            "type": typ,
            "properties": props,
            "provenance": prov(kind, loc),
            "freshness": freshness or "unknown",
            "verificationStatus": "unverified",
        }
        if coverage:
            n["coverageStatus"] = coverage
        nodes.append(n)

    def link(typ: str, s: str, t: str, kind: str, loc: str, freshness: str = "unknown") -> None:
        edges.append(
            {
                "id": f"rel:{typ}:{s}->{t}",
                "type": typ,
                "sourceId": s,
                "targetId": t,
                "provenance": prov(kind, loc),
                "freshness": freshness,
            }
        )

    for f in sorted((root / "requirements").glob("REQ-*.yml")):
        text = f.read_text(encoding="utf-8")
        uid = f.stem
        source = re.search(r"(?m)^source:\s*(.+)$", text)
        if source and source.group(1).strip() == "|":
            source = re.search(r"(?m)^source:\s*\|\s*\n\s+([^\n]+)", text)
        evidence = re.findall(r"(?m)^\s*-\s*\|?\s*\n?\s*([^\n]+\.py#[^\n]+)", text)
        coverage = (
            "untestable"
            if "Untestable:" in text
            else ("uncovered" if "Uncovered:" in text or not evidence else "notAssessed")
        )
        rid = "req:" + uid
        body = re.search(r"(?ms)^text:\s*\|\s*\n((?:[ \t]+.*\n?)*)", text)
        add(
            rid,
            "Requirement",
            {"uid": uid, "text": " ".join(x.strip() for x in body.group(1).splitlines()) if body else ""},
            "doorstop",
            f"{uid}; source={source.group(1).strip() if source else 'unknown'}",
            coverage,
        )
        if source:
            raw = source.group(1).strip().strip("'\"")
            source_path = raw.split("#", 1)[0].removeprefix("../")
            if source_path and source_path != "|":
                sid = "source:" + source_path
                state = fresh(source_path)
                if not any(n["id"] == sid for n in nodes):
                    add(sid, "Source", {"path": source_path}, "repository", source_path, freshness=state)
        for ref in evidence:
            ref = ref.strip()
            testpath, name = ref.split("#", 1)
            candidate = (f.parent / testpath).resolve()
            try:
                rel = candidate.relative_to(root).as_posix()
            except ValueError:
                rel = testpath
            tid = f"test:{rel}::{name}"
            state = fresh(rel)
            add(tid, "AutomatedTest", {"nodeid": f"{rel}::{name}"}, "repository", rel, freshness=state)
            link("verifiedBy", rid, tid, "doorstop", f"{uid}; evidence={ref}", state)
    analysis = root / "docs/qml-frontend-analysis.md"
    if analysis.exists():
        lines = analysis.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^\| (CAP-[A-Z0-9-]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|", line)
            if not match:
                continue
            cap, title, implementation, tests = (part.strip() for part in match.groups())
            cid = "cap:" + cap
            add(
                cid,
                "Capability",
                {"name": title},
                "capability-register",
                f"docs/qml-frontend-analysis.md#{cap}",
                "notAssessed",
                fresh("docs/qml-frontend-analysis.md"),
            )
            # Only explicit implementation paths in this inventory become relations.
            for path in re.findall(
                r"(?<![A-Za-z0-9_./-])[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|qml|ui)", implementation
            ):
                state = fresh(path)
                sid = "source:" + path
                if not any(n["id"] == sid for n in nodes):
                    add(sid, "Source", {"path": path}, "repository", path, freshness=state)
                link(
                    "implementedBy",
                    cid,
                    sid,
                    "capability-register",
                    f"docs/qml-frontend-analysis.md:{index + 1}",
                    state,
                )
            # Test references explicitly listed in the inventory are test definitions, not run evidence.
            for path, name in re.findall(r"([A-Za-z0-9_./-]+\.py)::(test_[A-Za-z0-9_]+)", tests):
                tid = f"test:{path}::{name}"
                state = fresh(path)
                if not any(n["id"] == tid for n in nodes):
                    add(tid, "AutomatedTest", {"nodeid": f"{path}::{name}"}, "repository", path, freshness=state)
                link("verifiedBy", cid, tid, "capability-register", f"docs/qml-frontend-analysis.md:{index + 1}", state)
    beadfile = root / ".beads/issues.jsonl"
    if beadfile.exists():
        for line in beadfile.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            iid = str(item["id"])
            bid = "beads:" + iid
            add(
                bid,
                "BeadsIssue",
                {"title": item.get("title", ""), "status": item.get("status", "unknown")},
                "beads",
                f"{iid}; updated_at={item.get('updated_at', 'unknown')}",
            )
            match = re.fullmatch(r"doorstop:(REQ-[0-9]+)", item.get("external_ref") or "")
            if match and any(n["id"] == "req:" + match.group(1) for n in nodes):
                link(
                    "trackedBy",
                    "req:" + match.group(1),
                    bid,
                    "beads",
                    f"{iid}; updated_at={item.get('updated_at', 'unknown')}",
                )
    return {
        "schemaId": SCHEMA,
        "repository": {"id": "doorstop-edit", "revision": commit},
        "generatedAt": now,
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: e["id"]),
    }


ALLOWED = {
    "derivedFrom": {("Capability", "Requirement"), ("Capability", "Source")},
    "implementedBy": {("Capability", "Source")},
    "verifiedBy": {(a, b) for a in ("Requirement", "Capability") for b in ("AutomatedTest", "ManualCase")},
    "trackedBy": {(a, "BeadsIssue") for a in ("Requirement", "Capability", "Source", "AutomatedTest")},
    "evidencedBy": {("AutomatedTest", "Evidence"), ("ManualCase", "Evidence")},
    "impacts": {
        (a, b) for a in ("Source", "Capability") for b in ("Requirement", "Capability", "AutomatedTest", "BeadsIssue")
    },
    "supersedes": set(),
}


NODE_TYPES = {"Requirement", "Capability", "Source", "AutomatedTest", "ManualCase", "BeadsIssue", "Evidence"}
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
ID_PATTERNS = {
    "Requirement": re.compile(r"req:[A-Za-z0-9_.-]+\Z"),
    "Capability": re.compile(r"cap:CAP-[A-Z0-9-]+\Z"),
    "Source": re.compile(r"source:[^\s#]+(?:::[^\s#]+)?\Z"),
    "AutomatedTest": re.compile(r"test:[^\s#]+::.+\Z"),
    "ManualCase": re.compile(r"manual:[A-Za-z0-9_.-]+\Z"),
    "BeadsIssue": re.compile(r"beads:[A-Za-z0-9_.-]+\Z"),
    "Evidence": re.compile(r"evidence:[^\s#]+#[^\s#]+\Z"),
}


def validate(graph: Any, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if not isinstance(graph, dict):
        return ["graph must be an object"]
    if graph.get("schemaId") != SCHEMA:
        errors.append("unsupported schemaId")
    try:
        datetime.fromisoformat(graph.get("generatedAt", ""))
    except (TypeError, ValueError):
        errors.append("invalid generatedAt")
    repo = graph.get("repository")
    if not isinstance(repo, dict) or repo.get("id") != "doorstop-edit" or not isinstance(repo.get("revision"), str):
        errors.append("invalid repository snapshot")
    elif repo["revision"] != "unknown" and not re.fullmatch(r"[0-9a-f]{40,64}", repo["revision"]):
        errors.append("invalid repository revision")
    ns = graph.get("nodes")
    es = graph.get("edges")
    if not isinstance(ns, list):
        errors.append("nodes must be an array")
        ns = []
    if not isinstance(es, list):
        errors.append("edges must be an array")
        es = []
    byid: dict[str, dict[str, Any]] = {}
    for i, n in enumerate(ns):
        if not isinstance(n, dict):
            errors.append(f"node {i} must be an object")
            continue
        ident, typ = n.get("id"), n.get("type")
        if not isinstance(typ, str) or typ not in NODE_TYPES:
            errors.append(f"invalid node type: {ident}")
            continue
        if not isinstance(ident, str) or not ID_PATTERNS[typ].fullmatch(ident):
            errors.append(f"invalid node id: {ident}")
            continue
        if ident in byid:
            errors.append(f"duplicate node id: {ident}")
            continue
        byid[ident] = n
        if not isinstance(n.get("properties"), dict):
            errors.append(f"invalid properties: {ident}")
        p = n.get("provenance")
        if not isinstance(p, dict):
            errors.append(f"missing provenance: {ident}")
            p = {}
        if not isinstance(p.get("sourceKind"), str) or p.get("sourceKind") not in PROVENANCE_KINDS:
            errors.append(f"invalid provenance sourceKind: {ident}")
        for key in ("sourceLocator", "observedAt", "method", "repositoryRevision"):
            if not isinstance(p.get(key), str) or not p[key]:
                errors.append(f"missing provenance {key}: {ident}")
        if not isinstance(p.get("method"), str) or p.get("method") not in ("automated", "manual", "derived"):
            errors.append(f"invalid provenance method: {ident}")
        if not isinstance(p.get("repositoryRevision"), str) or (
            p.get("repositoryRevision") != "unknown"
            and not re.fullmatch(r"[0-9a-f]{40,64}", p.get("repositoryRevision", ""))
        ):
            errors.append(f"invalid provenance revision: {ident}")
        if not isinstance(n.get("freshness"), str) or n.get("freshness") not in FRESHNESS:
            errors.append(f"invalid freshness: {ident}")
        if "verificationStatus" in n and (
            not isinstance(n["verificationStatus"], str) or n["verificationStatus"] not in VERIFY
        ):
            errors.append(f"invalid verificationStatus: {ident}")
        if "coverageStatus" in n and (not isinstance(n["coverageStatus"], str) or n["coverageStatus"] not in COVERAGE):
            errors.append(f"invalid coverageStatus: {ident}")
        if typ in ("Source", "AutomatedTest", "Evidence"):
            props: dict[str, Any] = n["properties"] if isinstance(n.get("properties"), dict) else {}
            locator = p.get("sourceLocator")
            if typ == "Source" and isinstance(locator, str):
                loc_path = locator.split("#", 1)[0].split("::", 1)[0]
                if ident != f"source:{props.get('path', '')}" or props.get("path") != loc_path:
                    errors.append(f"source ID/locator mismatch: {ident}")
            if typ == "AutomatedTest" and isinstance(locator, str):
                loc_path = locator.split("#", 1)[0].split("::", 1)[0]
                if not str(props.get("nodeid", "")).startswith(loc_path + "::") or not ident.startswith(
                    f"test:{loc_path}::"
                ):
                    errors.append(f"test ID/locator mismatch: {ident}")
            if typ == "Evidence" and isinstance(locator, str):
                expected_prefix = f"evidence:{locator.split('#', 1)[0]}#"
                if not ident.startswith(expected_prefix):
                    errors.append(f"evidence ID/locator mismatch: {ident}")
            loc = p.get("sourceLocator")
            if not isinstance(loc, str):
                continue
            path = loc.split("#", 1)[0].split("::", 1)[0]
            if not path or Path(path).is_absolute() or ".." in Path(path).parts:
                errors.append(f"invalid repository locator: {ident}")
                continue
            if n.get("freshness") == "current" and not (root / path).is_file():
                errors.append(f"current locator does not exist: {ident}")
            start, end = (
                n.get("properties", {}).get("lineStart"),
                n.get("properties", {}).get("lineEnd") if isinstance(n.get("properties"), dict) else (None, None),
            )
            if (start is None) != (end is None):
                errors.append(f"incomplete line range: {ident}")
            elif start is not None and (
                not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start
            ):
                errors.append(f"invalid line range: {ident}")
    seen: set[str] = set()
    for i, e in enumerate(es):
        if not isinstance(e, dict):
            errors.append(f"edge {i} must be an object")
            continue
        ident, typ = e.get("id"), e.get("type")
        source_id, target_id = e.get("sourceId"), e.get("targetId")
        s = byid.get(source_id) if isinstance(source_id, str) else None
        t = byid.get(target_id) if isinstance(target_id, str) else None
        if not s or not t:
            errors.append(f"broken edge endpoint: {ident}")
            continue
        if (
            not isinstance(typ, str)
            or typ not in ALLOWED
            or (s.get("type"), t.get("type")) not in ALLOWED.get(typ, set())
        ):
            errors.append(f"invalid edge type/endpoints: {ident}")
        expected = f"rel:{typ}:{e.get('sourceId')}->{e.get('targetId')}"
        if ident != expected or ident in seen:
            errors.append(f"invalid or duplicate edge id: {ident}")
        if isinstance(ident, str):
            seen.add(ident)
        if not isinstance(e.get("freshness"), str) or e.get("freshness") not in FRESHNESS:
            errors.append(f"invalid edge freshness: {ident}")
        p = e.get("provenance")
        if not isinstance(p, dict):
            errors.append(f"missing edge provenance: {ident}")
            continue
        if not isinstance(p.get("sourceLocator"), str) or not p.get("sourceLocator"):
            errors.append(f"missing edge locator: {ident}")
        if not isinstance(p.get("sourceKind"), str) or p.get("sourceKind") not in PROVENANCE_KINDS:
            errors.append(f"invalid edge provenance sourceKind: {ident}")
        for key in ("observedAt", "method", "repositoryRevision"):
            if not isinstance(p.get(key), str) or not p[key]:
                errors.append(f"missing edge provenance {key}: {ident}")
        if not isinstance(p.get("method"), str) or p.get("method") not in ("automated", "manual", "derived"):
            errors.append(f"invalid edge provenance method: {ident}")
        edge_rev = p.get("repositoryRevision")
        if not isinstance(edge_rev, str) or (edge_rev != "unknown" and not re.fullmatch(r"[0-9a-f]{40,64}", edge_rev)):
            errors.append(f"invalid edge provenance revision: {ident}")
    return errors


def status_report(graph: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Summarize explicit gaps and effective freshness without judging compliance."""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    gaps = sorted(
        f"{node.get('id')}: {node.get('coverageStatus')}"
        for node in nodes
        if isinstance(node, dict)
        and node.get("type") in ("Requirement", "Capability")
        and node.get("coverageStatus") in ("uncovered", "untestable")
    )
    current_rev = rev(root)
    snapshot = graph.get("repository", {}).get("revision") if isinstance(graph.get("repository"), dict) else None
    try:
        clean = not subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True, env=_git_env()
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        clean = False

    def effective(item: dict[str, Any]) -> str:
        state = item.get("freshness", "unknown")
        if state == "current":
            if not clean or current_rev == "unknown" or snapshot != current_rev:
                return "unknown" if not clean else "stale"
            provenance = item.get("provenance", {})
            if provenance.get("repositoryRevision") != snapshot:
                return "stale"
            loc = provenance.get("sourceLocator", "")
            if item.get("type") in ("Source", "AutomatedTest", "Evidence"):
                path = loc.split("#", 1)[0].split("::", 1)[0]
                if not (root / path).is_file():
                    return "stale"
            return "current"
        return state if state in FRESHNESS else "unknown"

    stale = sorted(
        item.get("id", "<invalid>")
        for item in [*nodes, *edges]
        if isinstance(item, dict) and effective(item) == "stale"
    )
    unknown = sorted(
        item.get("id", "<invalid>")
        for item in [*nodes, *edges]
        if isinstance(item, dict) and effective(item) == "unknown"
    )
    lines = ["Coverage gaps (not compliance failures):"]
    lines.extend(f"  {item}" for item in gaps) if gaps else lines.append("  none recorded")
    lines.append("Stale nodes/edges:")
    lines.extend(f"  {item}" for item in stale) if stale else lines.append("  none")
    lines.append("Unknown nodes/edges:")
    lines.extend(f"  {item}" for item in unknown) if unknown else lines.append("  none")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", metavar="FILE")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()
    try:
        graph = json.loads(Path(args.validate).read_text(encoding="utf-8")) if args.validate else build()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"traceability: {exc}", file=sys.stderr)
        return 2
    errors = validate(graph)
    if errors:
        print("\n".join("ERROR: " + x for x in errors), file=sys.stderr)
        return 1
    if args.validate:
        print(f"Valid graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges (no coverage claim)")
        print("\n".join(status_report(graph)))
    else:
        out = json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
        else:
            sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

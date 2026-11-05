"""Validate Doorstop requirements and their named traceability evidence."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import doorstop

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT / "requirements"
LINK_PATTERN = re.compile(r"^(.+?)(?:#(.+))?$")


def target_exists(value: str) -> bool:
    value = value.strip()
    match = LINK_PATTERN.fullmatch(value)
    if match is None or not match.group(2):
        return False
    path = (TREE / match.group(1)).resolve()
    if not path.is_relative_to(ROOT):
        return False
    anchor = match.group(2)
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return bool(re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(anchor)}\s*\(", content, re.M))
    if path.suffix in {".md", ".markdown"}:
        headings = re.findall(r"^#+\s+(.+?)\s*#*\s*$", content, re.M)

        def slug(heading: str) -> str:
            return re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", heading.lower()))

        return anchor in {slug(heading) for heading in headings}
    return False


def native_reference_errors(uid: str, references: list[dict[str, str]]) -> list[str]:
    errors = []
    for reference in references:
        if reference.get("type") != "file":
            errors.append(f"{uid}: unsupported native reference type: {reference.get('type', '')}")
            continue
        path = (ROOT / reference.get("path", "")).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            errors.append(f"{uid}: broken native reference path: {reference.get('path', '')}")
    return errors


def link_errors(uid: str, source: str, evidence: list[str]) -> list[str]:
    errors = []
    if not target_exists(source):
        errors.append(f"{uid}: broken source link: {source}")
    errors.extend(f"{uid}: broken evidence link: {value}" for value in evidence if not target_exists(value))
    return errors


def main() -> int:
    errors: list[str] = []
    try:
        tree = doorstop.build(cwd=str(TREE), root=str(TREE))
        for document in tree:
            for item in document.items:
                source = item.get("source", "")
                evidence = item.get("evidence", [])
                errors.extend(native_reference_errors(item.uid, item.get("references", [])))
                errors.extend(link_errors(item.uid, source, evidence))
                if not evidence:
                    print(f"UNCOVERED/UNTESTABLE {item.uid}: {item.get('review_note', 'No evidence declared.')}")
    except Exception as exc:
        print(f"Invalid Doorstop requirements tree: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

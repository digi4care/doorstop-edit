from pathlib import Path

import doorstop
import pytest

import tools.check_requirements as checker
from tools.check_requirements import link_errors, native_reference_errors


def test_broken_source_link_fails() -> None:
    assert link_errors("REQ-X", "../docs/missing.md#section", [])


def test_broken_named_evidence_target_fails() -> None:
    assert link_errors(
        "REQ-X",
        "../docs/validation-policy.md#decision",
        ["../doorstop_edit/test/test_application.py#missing_test"],
    )


def test_broken_native_reference_path_fails() -> None:
    assert native_reference_errors("REQ-X", [{"type": "file", "path": "docs/missing.md"}])


def test_uncovered_requirements_are_reported_without_failure() -> None:
    root = Path(__file__).resolve().parents[2]
    import subprocess

    result = subprocess.run(
        ["uv", "run", "python", str(root / "tools/check_requirements.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "UNCOVERED/UNTESTABLE REQ-004" in result.stdout


def test_checker_ignores_nested_doorstop_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    requirements = project_root / "requirements"
    expected_document = requirements / "REQ"
    nested_document = project_root / ".slim/worktrees/prototype/fixture/REQ"
    source = project_root / "docs/policy.md"
    evidence = project_root / "test/test_requirement_links.py"

    for document in (expected_document, nested_document):
        document.mkdir(parents=True)
        (document / ".doorstop.yml").write_text(
            "settings:\n  digits: 3\n  itemformat: yaml\n  prefix: REQ\n  sep: '-'\n",
            encoding="utf-8",
        )
    requirement = (
        "active: true\n"
        "derived: false\n"
        "evidence:\n"
        "- ../test/test_requirement_links.py#test_requirement\n"
        "header: Example\n"
        "level: 1.0\n"
        "links: []\n"
        "normative: true\n"
        "ref: ''\n"
        "references:\n"
        "- path: docs/policy.md\n"
        "  type: file\n"
        "source: ../docs/policy.md#decision\n"
        "text: A test requirement.\n"
        "verified: true\n"
    )
    nested_requirement = (
        "active: true\n"
        "derived: false\n"
        "header: Nested\n"
        "level: 1.0\n"
        "links: []\n"
        "normative: true\n"
        "ref: ''\n"
        "text: Nested fixture.\n"
    )
    (expected_document / "REQ-001.yml").write_text(requirement, encoding="utf-8")
    (nested_document / "REQ-001.yml").write_text(nested_requirement, encoding="utf-8")
    source.parent.mkdir(parents=True)
    source.write_text("# Decision\n\nRequirement source.\n", encoding="utf-8")
    evidence.parent.mkdir(parents=True)
    evidence.write_text("def test_requirement():\n    pass\n", encoding="utf-8")

    with pytest.raises(doorstop.DoorstopError, match="multiple root documents"):
        doorstop.build(cwd=str(project_root), root=str(project_root))

    monkeypatch.setattr(checker, "ROOT", project_root)
    monkeypatch.setattr(checker, "TREE", requirements)
    assert checker.main() == 0

from pathlib import Path
from unittest.mock import patch

import doorstop
import pytest
from doorstop import settings as doorstop_settings

from doorstop_edit.doorstop_data import ValidationFinding, collect_validation, configure_validation_policy
from tools.gen_sample_tree import generate_tree


def test_collect_validation_attributes_builtin_findings_without_parsing_message(tree_root: Path) -> None:
    # An item warning's own text need not contain a UID. A document-level finding
    # must not be attributed to the last item in the preceding document.
    first_uid = ""
    with patch.object(doorstop.Tree, "get_issues", autospec=True) as get_issues:

        def issues(tree, *, document_hook, item_hook):
            from doorstop.common import DoorstopWarning

            nonlocal first_uid
            docs = list(tree)
            first = next(iter(docs[0]))
            first_uid = str(first.uid)
            yield from document_hook(document=docs[0], tree=tree)
            yield from item_hook(item=first, document=docs[0], tree=tree)
            yield DoorstopWarning("no text")
            yield from document_hook(document=docs[1], tree=tree)
            yield DoorstopWarning("no items")

        get_issues.side_effect = issues
        findings = collect_validation(tree_root)

    assert findings == [
        ValidationFinding("warning", "no text", first_uid),
        ValidationFinding("warning", "no items", None),
    ]


def test_validation_policy_stays_stable_and_does_not_write_item_files(tree_root: Path) -> None:
    configure_validation_policy()
    expected_settings = (
        doorstop_settings.REFORMAT,
        doorstop_settings.REVIEW_NEW_ITEMS,
        doorstop_settings.REORDER,
    )
    assert expected_settings == (False, False, False)
    item_paths = sorted(tree_root.rglob("REQ-*.yml"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in item_paths}
    real_get_issues = doorstop.Tree.get_issues

    def check_settings_during_validation(tree, **kwargs):
        for issue in real_get_issues(tree, **kwargs):
            assert (
                doorstop_settings.REFORMAT,
                doorstop_settings.REVIEW_NEW_ITEMS,
                doorstop_settings.REORDER,
            ) == expected_settings
            yield issue

    with patch.object(doorstop.Tree, "get_issues", autospec=True, side_effect=check_settings_during_validation):
        collect_validation(tree_root)
    assert (
        doorstop_settings.REFORMAT,
        doorstop_settings.REVIEW_NEW_ITEMS,
        doorstop_settings.REORDER,
    ) == expected_settings
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in item_paths} == before


def test_malformed_item_is_attributed_and_remaining_checks_are_explicit(tmp_path: Path) -> None:
    configure_validation_policy()
    generate_tree(tmp_path, 1, 2)
    bad = next(tmp_path.rglob("REQ-A-001.yml"))
    bad.write_text("text: [\n", encoding="utf-8")

    findings = collect_validation(tmp_path)

    assert any(f.severity == "error" and f.item_uid == "REQ-A-001" and "YAML" in f.message for f in findings)
    assert any(f.item_uid is None and "not run" in f.message for f in findings)


@pytest.mark.parametrize("malformed", ["level: bad\n", "references: null\n"])
def test_doorstop_item_load_exceptions_are_attributed(tmp_path: Path, malformed: str) -> None:
    configure_validation_policy()
    generate_tree(tmp_path, 1, 2)
    bad = next(tmp_path.rglob("REQ-A-001.yml"))
    bad.write_text(malformed, encoding="utf-8")

    findings = collect_validation(tmp_path)

    assert any(f.severity == "error" and f.item_uid == "REQ-A-001" for f in findings)
    assert any(f.severity == "info" and f.item_uid is None and "not run" in f.message for f in findings)

"""REQ-004: Validation findings must never prevent saving or editing.

These tests inject validation findings through the same result hook the real
validation service uses (``DoorstopEdit._on_validation_run_result``) and then
drive the application's normal save/edit paths, asserting that saving proceeds
and no modal dialog blocks the editor.
"""

from pathlib import Path
from unittest.mock import patch

import doorstop
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from doorstop_edit.application import DoorstopEdit
from doorstop_edit.doorstop_data import ValidationFinding
from doorstop_edit.test.test_application import (
    app,
    app_session,
    click_item_in_tree,
    type_in_search_box,
)
from doorstop_edit.validation_service import ValidationRunResult

# Marks the imported fixtures/helpers as intentionally re-used (pytest fixtures).
__all__ = ["app", "app_session"]


def _run_result(app: DoorstopEdit, findings: list[ValidationFinding]) -> ValidationRunResult:
    """Build a succeeded ValidationRunResult for the currently opened project."""
    root = app.doorstop_data.root
    assert root is not None
    now = "2026-01-01T00:00:00+00:00"
    return ValidationRunResult(
        str(root.resolve()),
        app.doorstop_data.content_revision,
        "req004-test-run",
        tuple(findings),
        "succeeded",
        now,
        now,
        None,
        str(root.resolve()),
    )


def _inject_error_finding(app: DoorstopEdit) -> None:
    """Surface a validation error for REQ-A-001 exactly as the app would."""
    app._on_validation_run_result(
        _run_result(app, [ValidationFinding("error", "REQ-A: REQ-A-001: broken link", "REQ-A-001")])
    )


def test_validation_findings_do_not_block_save(qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    _inject_error_finding(app)
    assert "1 error" in app.validation_status.text()

    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    item_path = Path(item.path)
    original_content = item_path.read_text("utf-8")

    item.text = f"{item.text}\nreq004-save-note"
    with patch.object(doorstop.Item, "save", wraps=item.save) as item_save:
        with qtbot.waitSignal(app.doorstop_data.item_saved, timeout=5000):
            app.doorstop_data.save_item(item)

    assert item_save.call_count == 1
    new_content = item_path.read_text("utf-8")
    assert new_content != original_content
    assert "req004-save-note" in new_content

    # Findings must not surface as a blocking modal; the editor stays usable.
    assert QApplication.activeModalWidget() is None
    assert app.window.ui.item_edit_uid.isEnabled()


def test_validation_findings_do_not_block_edit(qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    _inject_error_finding(app)
    assert "1 error" in app.validation_status.text()

    type_in_search_box(qtbot, app.window.ui, "REQ-A-002")
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 1
    click_item_in_tree(qtbot, app.window.ui, index=0)
    assert app.window.ui.item_edit_uid.text() == "REQ-A-002"

    item = app.doorstop_data.find_item("REQ-A-002")
    assert item is not None
    item_path = Path(item.path)
    original_content = item_path.read_text("utf-8")

    # Type into the editor; the app's debounced autosave must still write the file.
    with patch.object(doorstop.Item, "save", wraps=item.save) as item_save:
        with qtbot.wait_signal(app.window.ui.item_edit_text_text_edit.textChanged):
            qtbot.keyClicks(app.window.ui.item_edit_text_text_edit, "req004-edit-note")
        assert item_save.call_count == 0
        qtbot.wait(1000)  # Autosave fires 700 ms after typing stops.
        assert item_save.call_count == 1

    new_content = item_path.read_text("utf-8")
    assert new_content != original_content
    assert "req004-edit-note" in new_content

    assert QApplication.activeModalWidget() is None
    # Editing another field remains possible while findings are present.
    assert app.window.ui.item_edit_active_check_box.isEnabled()

import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator, cast
from unittest.mock import patch

import doorstop
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from doorstop_edit import application as application_module
from doorstop_edit.application import DoorstopEdit, QFileDialog
from doorstop_edit.conftest import NUM_DOC
from doorstop_edit.dialogs import ConfirmDialog, InfoDialog
from doorstop_edit.document_dialog import AddDocumentDialog
from doorstop_edit.doorstop_data import ValidationFinding
from doorstop_edit.ui_gen.ui_main import Ui_MainWindow
from doorstop_edit.validation_service import ValidationRunResult
from tools.gen_sample_tree import generate_tree


@pytest.fixture(scope="session")
def app_session(tree_root: Path) -> Iterator[DoorstopEdit]:
    """Create DoorstopEdit

    Created only once per session since QApplcation cannot be recreated reliably in a process, thus
    it is hard to recreate DoorstopEdit for each test.

    When DoorstopEdit is recreate QApplication still have references to the old instance which cause
    troubles.
    """
    app = DoorstopEdit(tree_root)
    app.start()  # Must show it, clicks wont work otherwise.
    app.doorstop_data.stop()
    yield app
    app.quit()


@pytest.fixture()
def app(
    app_session: DoorstopEdit, tree_root: Path, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> Iterator[DoorstopEdit]:
    # Reset directory
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", classmethod(lambda *_: str(tree_root)))
    with qtbot.wait_signal(app_session.window.ui.menu_action_open_folder.triggered):
        app_session.window.ui.menu_action_open_folder.trigger()

    # Reset document tree to the default document for each test.
    app_session.window.ui.tree_combo_box.setCurrentIndex(0)

    yield app_session


def count_items_in_current_document(app: DoorstopEdit) -> int:
    count = 0
    for _ in app.selected_document or []:
        count += 1
    return count


def click_item_in_tree(qtbot: QtBot, ui: Ui_MainWindow, index: int) -> None:
    w_item = ui.item_tree_widget.topLevelItem(index)
    assert w_item is not None
    w_item_rect = ui.item_tree_widget.visualItemRect(w_item)
    with qtbot.wait_signal(ui.item_tree_widget.itemSelectionChanged):
        qtbot.mouseClick(
            ui.item_tree_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            w_item_rect.center(),
        )


def click_button_clear_search(qtbot: QtBot, ui: Ui_MainWindow) -> None:
    with qtbot.wait_signal(ui.item_tree_search_input.textChanged):
        qtbot.mouseClick(ui.item_tree_clear_search, Qt.MouseButton.LeftButton)
    assert ui.item_tree_search_input.text() == ""


def type_in_search_box(qtbot: QtBot, ui: Ui_MainWindow, text: str) -> None:
    with qtbot.wait_signal(ui.item_tree_search_input.textChanged):
        ui.item_tree_search_input.clear()
        qtbot.keyClicks(ui.item_tree_search_input, text)


def test_select_tree_item_show_in_edit(qtbot: QtBot, app: DoorstopEdit) -> None:
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 1
    assert app.window.ui.item_edit_uid.text() == ""
    click_item_in_tree(qtbot, app.window.ui, index=0)
    assert app.window.ui.item_edit_uid.text() == "REQ-A-001"

    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None

    assert app.window.ui.item_edit_review_status_label.text() == "NOT REVIEWED"
    assert app.window.ui.item_edit_active_check_box.isChecked() == item.active
    assert app.window.ui.item_edit_normative_check_box.isChecked() == item.normative
    assert app.window.ui.item_edit_derived_check_box.isChecked() == item.derived
    assert app.window.ui.item_edit_level_line_edit.text() == str(item.level)
    assert app.window.ui.item_edit_text_text_edit.toPlainText() == item.text


def test_search_tree_item(qtbot: QtBot, app: DoorstopEdit) -> None:
    type_in_search_box(qtbot, app.window.ui, "REQ-B-004")  # Does not exist in current document
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 0

    click_button_clear_search(qtbot, app.window.ui)

    type_in_search_box(qtbot, app.window.ui, "REQ-A-003")
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 1

    click_item_in_tree(qtbot, app.window.ui, index=0)

    assert app.window.ui.item_edit_uid.text() == "REQ-A-003"


def test_change_document(qtbot: QtBot, app: DoorstopEdit) -> None:
    assert app.window.ui.tree_combo_box.count() == NUM_DOC
    qtbot.keyClicks(app.window.ui.tree_combo_box, "REQ-B")
    type_in_search_box(qtbot, app.window.ui, "REQ-B-007")
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 1
    click_item_in_tree(qtbot, app.window.ui, index=0)
    assert app.window.ui.item_edit_uid.text() == "REQ-B-007"


def test_edit_item_then_save(qtbot: QtBot, app: DoorstopEdit) -> None:
    type_in_search_box(qtbot, app.window.ui, "REQ-A-001")
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 1
    click_item_in_tree(qtbot, app.window.ui, index=0)

    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    item_path = Path(item.path)
    item_file_content = item_path.read_text("utf-8")

    with patch.object(doorstop.Item, "save", wraps=item.save) as item_save:
        with qtbot.wait_signal(app.window.ui.item_edit_text_text_edit.textChanged):
            added_text = "Some more content"
            qtbot.keyClicks(app.window.ui.item_edit_text_text_edit, added_text)
            assert item_save.call_count == 0
            qtbot.wait(1000)  # Should save after a period no typing.
            assert item_save.call_count == 1

    new_content = item_path.read_text("utf-8")
    assert item_file_content != new_content
    assert added_text in new_content


def test_document_reorder(qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfirmDialog, "ask", classmethod(lambda *_: True))

    with patch.object(doorstop.Document, "reorder") as doc_reorder_mock:
        with qtbot.wait_signal(app.window.ui.doc_reorder_level_tool_button.clicked):
            qtbot.mouseClick(app.window.ui.doc_reorder_level_tool_button, Qt.MouseButton.LeftButton)

    assert doc_reorder_mock.call_count == 1


def test_document_review_all(qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfirmDialog, "ask", classmethod(lambda *_: True))

    with patch.object(doorstop.Item, "review") as item_review_mock:
        with qtbot.wait_signal(app.window.ui.doc_review_tool_button.clicked):
            qtbot.mouseClick(app.window.ui.doc_review_tool_button, Qt.MouseButton.LeftButton)

    assert item_review_mock.call_count == count_items_in_current_document(app)


def test_document_clear_all_suspect_links(qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfirmDialog, "ask", classmethod(lambda *_: True))

    with patch.object(doorstop.Item, "clear") as item_clear_mock:
        with qtbot.wait_signal(app.window.ui.doc_clear_links_tool_button.clicked):
            qtbot.mouseClick(app.window.ui.doc_clear_links_tool_button, Qt.MouseButton.LeftButton)

    assert item_clear_mock.call_count == count_items_in_current_document(app)


def test_open_folder(qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch, tree_root: Path) -> None:
    monkeypatch.setattr(
        InfoDialog, "inform", classmethod(lambda *_: None)
    )  # We will open an empty directory which will trigger an inform.

    try:
        with tempfile.TemporaryDirectory() as tempDir, patch.object(doorstop, "build") as doorstop_build:
            monkeypatch.setattr(QFileDialog, "getExistingDirectory", classmethod(lambda *_: tempDir))
            with qtbot.wait_signal(app.window.ui.menu_action_open_folder.triggered):
                app.window.ui.menu_action_open_folder.trigger()

            assert doorstop_build.call_count == 1
    finally:
        app._rebuild_root(new_root=tree_root)


def _run_result(
    app: DoorstopEdit,
    findings: tuple[ValidationFinding, ...] | list[ValidationFinding] = (),
    *,
    state: str = "succeeded",
    error: str | None = None,
) -> ValidationRunResult:
    root = app.doorstop_data.root
    assert root is not None
    now = "2026-01-01T00:00:00+00:00"
    return ValidationRunResult(
        str(root.resolve()),
        app.doorstop_data.content_revision,
        "test-run",
        tuple(findings),
        state,
        now,
        now,
        error,
        str(root.resolve()),
    )


def _wait_for_validation_idle(qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(
        lambda: (
            not app._validation_running
            and app.validation_service._active is None
            and app.validation_service._pending is None
            and not app.validation_service._starting
        )
    )


def test_validation_action_and_tree_feedback(qtbot: QtBot, app: DoorstopEdit) -> None:
    app.window.ui.item_tree_search_input.clear()
    app.window.ui.tree_combo_box.setCurrentIndex(0)
    _wait_for_validation_idle(qtbot, app)
    result = [
        ValidationFinding("error", "REQ-A: REQ-A-001: broken link", "REQ-A-001"),
        ValidationFinding("warning", "REQ-A: REQ-A-002: no text", "REQ-A-002"),
    ]
    app._on_validation_run_result(_run_result(app, result))

    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None
    assert row.text(1).startswith("✕ ")
    assert "broken link" in row.toolTip(1)
    assert "1 error" in app.validation_status.text()
    assert "1 warning" in app.validation_status.text()
    app.window.ui.item_tree_search_input.setText("REQ-A-002")
    warning_row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert warning_row is not None
    assert warning_row.data(app.tree_view.UID_COLUMN, Qt.ItemDataRole.UserRole) == "REQ-A-002"
    assert warning_row.text(1).startswith("⚠ ")
    assert "no text" in warning_row.toolTip(1)
    app.validation_status.click()
    assert "broken link" in app.validation_dialog.toPlainText()


def test_validation_requests_coalesce_while_running(qtbot: QtBot, app: DoorstopEdit) -> None:
    _wait_for_validation_idle(qtbot, app)
    service = app.validation_service
    with patch.object(service, "request") as request:
        app._request_validation()
        app._request_validation()
        assert request.call_count == 2
        assert request.call_args.args == (app.doorstop_data.root, app.doorstop_data.content_revision)


def test_successful_item_save_requests_validation(qtbot: QtBot, app: DoorstopEdit) -> None:
    _wait_for_validation_idle(qtbot, app)
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    app.doorstop_data.save_item(item)
    _wait_for_validation_idle(qtbot, app)
    assert app.validation_status.text().startswith("Validation ·")


def test_validation_failure_keeps_existing_markers(qtbot: QtBot, app: DoorstopEdit) -> None:
    _wait_for_validation_idle(qtbot, app)
    existing = [ValidationFinding("warning", "Existing warning", "REQ-A-001")]
    app._on_validation_run_result(_run_result(app, existing))
    app._on_validation_run_result(_run_result(app, (), state="failed", error="Invalid item"))
    assert app.validation_status.text() == "Validation could not complete"
    assert "Invalid item" in app.validation_dialog.toPlainText()
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None
    assert "Existing warning" in row.toolTip(1)


def test_open_project_with_malformed_item_shows_error_marker(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    generate_tree(tmp_path, 1, 2)
    next(tmp_path.rglob("REQ-A-001.yml")).write_text("text: [\n", encoding="utf-8")
    app.window.ui.item_tree_search_input.clear()

    app._rebuild_root(new_root=tmp_path)
    qtbot.waitUntil(lambda: app.validation_status.text().startswith("Validation ·"))

    rows = [
        app.window.ui.item_tree_widget.topLevelItem(i)
        for i in range(app.window.ui.item_tree_widget.topLevelItemCount())
    ]
    assert all(row is not None for row in rows)
    bad_row = next(
        (
            row
            for row in rows
            if row is not None and row.data(app.tree_view.UID_COLUMN, Qt.ItemDataRole.UserRole) == "REQ-A-001"
        ),
        None,
    )
    assert bad_row is not None
    assert bad_row.text(1).startswith("✕ ")
    assert "YAML" in bad_row.toolTip(1)


def test_add_document_selects_created_child(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    assert app.selected_document is not None
    assert app.selected_document.prefix == "REQ-A"

    def fill_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, AddDocumentDialog)
        assert dialog.parent_combo.currentData() == "REQ-A"
        assert dialog.parent_combo.count() == 1
        assert dialog.parent_combo.itemText(0) == "REQ-A"
        dialog.prefix_edit.setText("CHILD")
        qtbot.keyClick(dialog.prefix_edit, Qt.Key.Key_Return)

    QTimer.singleShot(0, fill_dialog)
    qtbot.mouseClick(app.window.ui.add_document_button, Qt.MouseButton.LeftButton)
    assert app.window.ui.tree_combo_box.currentData() == "CHILD"
    assert app.selected_document is not None and app.selected_document.prefix == "CHILD"
    child = app.doorstop_data.find_document("CHILD")
    assert child is not None
    assert child.parent == "REQ-A"
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 0
    assert app.window.ui.item_edit_uid.text() == ""


def test_add_document_invalid_prefix_stays_open_and_cancel_does_not_create(
    tmp_path: Path, qtbot: QtBot, app: DoorstopEdit
) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    original = set(tmp_path.rglob(".doorstop.yml"))

    def try_invalid_then_cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, AddDocumentDialog)
        dialog.create_button.click()
        assert dialog.isVisible()
        assert "required" in dialog.error_label.text().lower()
        dialog.prefix_edit.setText("BAD/NAME")
        dialog.create_button.click()
        assert dialog.isVisible()
        assert dialog.error_label.text()
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(0, try_invalid_then_cancel)
    qtbot.mouseClick(app.window.ui.add_document_button, Qt.MouseButton.LeftButton)
    assert set(tmp_path.rglob(".doorstop.yml")) == original
    assert app.window.ui.tree_combo_box.currentData() == "REQ-A"


@pytest.mark.parametrize("invalid_prefix", ["BAD NAME", "BAD "])
def test_add_document_whitespace_is_rejected_without_normalizing(
    tmp_path: Path, qtbot: QtBot, app: DoorstopEdit, invalid_prefix: str
) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    original = set(tmp_path.rglob(".doorstop.yml"))
    observed = []

    def try_invalid_then_escape() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, AddDocumentDialog)
        dialog.prefix_edit.setText(invalid_prefix)
        try:
            qtbot.keyClick(dialog.prefix_edit, Qt.Key.Key_Return)
            observed.append((dialog.isVisible(), dialog.prefix_edit.text(), dialog.error_label.text()))
        finally:
            qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(0, try_invalid_then_escape)
    qtbot.mouseClick(app.window.ui.add_document_button, Qt.MouseButton.LeftButton)
    assert len(observed) == 1
    assert observed[0][:2] == (True, invalid_prefix)
    assert "whitespace" in observed[0][2].lower()
    assert set(tmp_path.rglob(".doorstop.yml")) == original
    assert app.window.ui.tree_combo_box.currentData() == "REQ-A"


def test_remove_leaf_refreshes_selection_and_editor(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    app.doorstop_data.create_document("LEAF", parent="REQ-A")
    app.window.ui.tree_combo_box.setCurrentIndex(app.window.ui.tree_combo_box.findData("LEAF"))
    assert app.selected_document is not None
    leaf_path = Path(app.selected_document.path)

    def confirm() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        assert dialog.defaultButton().text() == "Cancel"
        assert "LEAF" in dialog.text()
        next(button for button in dialog.buttons() if button.text() == "Remove document").click()

    QTimer.singleShot(0, confirm)
    qtbot.mouseClick(app.window.ui.remove_document_button, Qt.MouseButton.LeftButton)
    assert not (leaf_path / ".doorstop.yml").exists()
    assert app.doorstop_data.find_document("LEAF") is None
    assert app.window.ui.tree_combo_box.findData("LEAF") == -1
    assert app.selected_document is not None and app.selected_document.prefix == "REQ-A"
    assert app.window.ui.item_edit_uid.text() == ""


def test_remove_parent_with_children_blocked_before_confirmation(
    tmp_path: Path, qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    app.doorstop_data.create_document("CHILD", parent="REQ-A")
    app.window.ui.tree_combo_box.setCurrentIndex(app.window.ui.tree_combo_box.findData("REQ-A"))
    configs = set(tmp_path.rglob(".doorstop.yml"))
    parent_items = {path: path.read_bytes() for path in (tmp_path / "REQ-A").glob("REQ-A-*.yml")}
    assert parent_items
    notices = []
    monkeypatch.setattr(InfoDialog, "inform", lambda _parent, title, text: notices.append((title, text)))
    with patch.object(QMessageBox, "exec", side_effect=AssertionError("Confirmation must not open")):
        qtbot.mouseClick(app.window.ui.remove_document_button, Qt.MouseButton.LeftButton)
    assert "CHILD" in notices[0][1]
    assert set(tmp_path.rglob(".doorstop.yml")) == configs
    assert {path: path.read_bytes() for path in (tmp_path / "REQ-A").glob("REQ-A-*.yml")} == parent_items
    assert app.window.ui.tree_combo_box.currentData() == "REQ-A"
    assert app.doorstop_data.find_document("CHILD") is not None


def test_remove_without_selection_disabled_and_confirmation_cancel_keeps_document(
    tmp_path: Path, qtbot: QtBot, app: DoorstopEdit
) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    combo = app.window.ui.tree_combo_box
    combo.setCurrentIndex(-1)
    assert not app.window.ui.remove_document_button.isEnabled()
    combo.setCurrentIndex(combo.findData("REQ-A"))

    def cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        dialog.defaultButton().click()

    QTimer.singleShot(0, cancel)
    qtbot.mouseClick(app.window.ui.remove_document_button, Qt.MouseButton.LeftButton)
    assert app.doorstop_data.find_document("REQ-A") is not None
    assert next(tmp_path.rglob(".doorstop.yml")).exists()


def test_remove_last_document_shows_empty_state(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    generate_tree(tmp_path, 1, 1)
    # The sample generator adds an unmanaged image directory; remove that fixture artifact
    # so this test exercises the final-document path rather than the data-layer safety guard.
    shutil.rmtree(tmp_path / "REQ-A" / "images")
    app._rebuild_root(new_root=tmp_path)

    def confirm() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        next(button for button in dialog.buttons() if button.text() == "Remove document").click()
        QTimer.singleShot(0, dismiss_unexpected_error)

    def dismiss_unexpected_error() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            error_messages.append(dialog.text())
            dialog.accept()

    error_messages: list[str] = []
    QTimer.singleShot(0, confirm)
    qtbot.mouseClick(app.window.ui.remove_document_button, Qt.MouseButton.LeftButton)
    assert not error_messages, error_messages
    assert app.window.ui.tree_combo_box.count() == 0
    assert app.selected_document is None
    assert not app.window.ui.remove_document_button.isEnabled()
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 0
    assert app.window.ui.item_edit_uid.text() == ""
    assert app.window.ui.add_document_button.isEnabled()


def test_remove_backend_error_reports_uncertain_state(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    messages = []

    def confirm_then_dismiss_error() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        next(button for button in dialog.buttons() if button.text() == "Remove document").click()
        QTimer.singleShot(0, read_error)

    def read_error() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        messages.append(dialog.text())
        dialog.accept()

    with patch.object(app.doorstop_data, "remove_document", side_effect=doorstop.DoorstopError("Permission denied")):
        QTimer.singleShot(0, confirm_then_dismiss_error)
        qtbot.mouseClick(app.window.ui.remove_document_button, Qt.MouseButton.LeftButton)
    assert "Permission denied" in messages[0]
    assert "Check the project" in messages[0]
    assert app.doorstop_data.find_document("REQ-A") is not None


def test_remove_refresh_failure_warns_and_disables_stale_editor(
    qtbot: QtBot, tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_tree(tmp_path, 1, 1)
    shutil.rmtree(tmp_path / "REQ-A" / "images", ignore_errors=True)
    app._rebuild_root(new_root=tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(
        application_module.QMessageBox,
        "warning",
        lambda _parent, _title, text: messages.append(text),
    )

    def confirm_removal(dialog: QMessageBox) -> int:
        next(button for button in dialog.buttons() if button.text() == "Remove document").click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", confirm_removal)

    def fail_rebuild(*_args: object, **_kwargs: object) -> None:
        raise doorstop.DoorstopError("simulated reload failure")

    monkeypatch.setattr(app.doorstop_data, "rebuild", fail_rebuild)
    app._on_remove_document_clicked()

    assert not (tmp_path / "REQ-A").exists()
    assert app.doorstop_data.tree_stale
    assert "tree may be stale" in messages[0]
    assert "reopen or reload" in messages[0].lower()
    assert not app.window.ui.tree_combo_box.isEnabled()
    assert not app.window.ui.add_document_button.isEnabled()
    assert not app.window.ui.remove_document_button.isEnabled()
    assert app.item_edit_view.item is None


def test_stale_document_tree_remains_disabled_after_tree_change(qtbot: QtBot, app: DoorstopEdit) -> None:
    app._mark_document_tree_stale()
    app._on_tree_changed(modified_only=False)

    assert not app.window.ui.tree_combo_box.isEnabled()
    assert not app.window.ui.add_document_button.isEnabled()
    assert not app.window.ui.remove_document_button.isEnabled()
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 0
    assert app.window.ui.item_edit_uid.text() == ""


def test_validation_service_retains_temp_while_process_runs(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    service = ValidationService()
    polled: list[bool] = []

    class UnfinishedOwner:
        group_id = 1
        supervisor_reaped = False
        _termination_confirmed = True

        def poll_helper(self) -> int | None:
            polled.append(True)
            return None

        def read_status(self) -> bytes | None:
            polled.append(True)
            return None

        def signal_group(self) -> None:
            pass

        def reap_supervisor(self, timeout: float = 0.5) -> Any:
            self.supervisor_reaped = True
            return type("ReapResult", (), {"supervisor_reaped": True})()

        def confirm_group_absent(self, timeout: float = 0.5) -> bool:
            return True

        def terminate_tree(self, timeout: float = 0.5) -> bool:
            return True

        def close(self, timeout: float = 0.5) -> bool:
            return True

    owner = UnfinishedOwner()
    monkeypatch.setattr(service, "_launch_owner", lambda *args: owner)
    service.request(tmp_path, 4)
    run = service._active
    assert run is not None
    result_dir = run.temp_dir
    qtbot.waitUntil(lambda: bool(polled), timeout=5000)
    assert result_dir.exists(), "uncompleted helper must retain its result directory"
    service.shutdown()
    assert run.cleanup_event.wait(5)
    qtbot.waitUntil(lambda: service._active is None, timeout=5000)


def test_quit_marks_shutdown_before_stopping_watcher(qtbot: QtBot, app: DoorstopEdit) -> None:
    original_stop = app.doorstop_data.stop
    observed: list[bool] = []

    def stop_watcher() -> None:
        observed.append(app._shutting_down)
        original_stop()

    with (
        patch.object(app.doorstop_data, "stop", side_effect=stop_watcher),
        patch.object(app.validation_service, "shutdown"),
        patch.object(app.item_render_view, "destroy"),
        patch.object(app.window, "close"),
    ):
        app.quit()

    # The session-scoped app is reused by later tests; keep it operational.
    app._shutting_down = False
    assert observed == [True]


def test_external_valid_to_invalid_item_clears_editor_and_blocks_save(qtbot: QtBot, app: DoorstopEdit) -> None:
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    path = Path(item.path)
    valid_contents = path.read_text(encoding="utf-8")
    app.item_edit_view.update_item(item)

    path.write_text("level: bad\n", encoding="utf-8")
    try:
        app.doorstop_data._on_filewatch_callback(True, (str(path),), app.doorstop_data.file_watcher.generation)

        assert app.doorstop_data.get_item_load_error("REQ-A-001")
        assert app.item_edit_view.item is None
        with pytest.raises(ValueError, match="Cannot save invalid item"):
            app.doorstop_data.save_item(item)
        assert path.read_text(encoding="utf-8") == "level: bad\n"
    finally:
        path.write_text(valid_contents, encoding="utf-8")
        app.doorstop_data._on_filewatch_callback(True, (str(path),), app.doorstop_data.file_watcher.generation)
    assert app.doorstop_data.get_item_load_error("REQ-A-001") is None


def test_save_checks_disk_before_watcher_and_preserves_editor_item(qtbot: QtBot, app: DoorstopEdit) -> None:
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    path = Path(item.path)
    original_contents = path.read_text(encoding="utf-8")
    item.text = "Unsaved editor buffer"
    path.write_text("text: [\n", encoding="utf-8")

    try:
        with pytest.raises(ValueError, match="Cannot save invalid item"):
            app.doorstop_data.save_item(item)

        assert "Unsaved editor buffer" in str(item.text)
        assert path.read_text(encoding="utf-8") == "text: [\n"
        assert app.doorstop_data.get_item_load_error("REQ-A-001")
    finally:
        path.write_text(original_contents, encoding="utf-8")
        app.doorstop_data._on_filewatch_callback(True, (str(path),), app.doorstop_data.file_watcher.generation)


def test_project_switch_cancels_pending_save_even_for_same_uid(
    tmp_path: Path, tree_root: Path, qtbot: QtBot, app: DoorstopEdit
) -> None:
    old_root = tmp_path / "old-project"
    old_root.mkdir()
    generate_tree(old_root, 1, 2)
    app._rebuild_root(new_root=old_root)
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    old_path = Path(item.path)
    old_original = old_path.read_text(encoding="utf-8")
    app.item_edit_view.update_item(item)
    app.window.ui.item_edit_text_text_edit.setPlainText("pending old project edit")
    assert app.item_edit_view._save_timer.isActive()

    new_root = tmp_path / "same-prefix-project"
    new_root.mkdir()
    generate_tree(new_root, 1, 2)
    app._rebuild_root(new_root=new_root)
    qtbot.wait(800)

    new_path = next(new_root.rglob("REQ-A-001.yml"))
    assert app.item_edit_view.item is None
    assert not app.item_edit_view._save_timer.isActive()
    assert old_path.read_text(encoding="utf-8") == old_original
    assert "pending old project edit" not in new_path.read_text(encoding="utf-8")


def test_valid_item_renders_with_malformed_sibling(tmp_path: Path, app: DoorstopEdit) -> None:
    generate_tree(tmp_path, 1, 2)
    next(tmp_path.rglob("REQ-A-002.yml")).write_text("text: [\n", encoding="utf-8")
    app._rebuild_root(new_root=tmp_path)
    valid = app.doorstop_data.find_item("REQ-A-001")
    assert valid is not None

    app.item_render_view.show(valid, force_reload=True)

    assert app.doorstop_data.get_item_load_error("REQ-A-002")
    assert app.item_render_view._viewed_item is valid


def test_stale_render_generation_is_ignored_after_project_clear(app: DoorstopEdit) -> None:
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    view = app.item_render_view
    view.show(item)
    stale_generation = view._render_generation
    view.show(None)
    updates: list[tuple[str, str, bool, bool]] = []
    view.html_update_item.connect(lambda *args: updates.append(args))
    view._on_render_finished("REQ-A-001", "old project html", stale_generation)
    assert updates == []


def test_selection_before_prior_render_completion_forces_full_batch(app: DoorstopEdit) -> None:
    first = app.doorstop_data.find_item("REQ-A-001")
    second = app.doorstop_data.find_item("REQ-A-002")
    assert first is not None and second is not None
    view = app.item_render_view
    view.show(first)
    old_generation = view._render_generation
    # The old worker batch may already have populated its cache, but its result
    # and completion callbacks have not yet been applied to the page.
    view.show(second)
    assert not view._render_generation_ready
    with patch.object(view._render_worker, "render") as render:
        view._render_items(partial=True)

    render.assert_called_once()
    assert render.call_args.args[2] is False
    assert render.call_args.args[3] == view._render_generation
    assert view._render_generation != old_generation


def test_force_reload_invalidates_same_item_render_generation(app: DoorstopEdit) -> None:
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    view = app.item_render_view
    view.show(item)
    view._on_render_batch_finished(view._render_generation)
    generation = view._render_generation

    view.show(item, force_reload=True)

    assert view._render_generation == generation + 1
    assert not view._render_generation_ready


def test_failed_root_rebuild_preserves_current_tree_and_watcher(
    tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_root = app.doorstop_data.root
    original_tree = app.doorstop_data._tree
    original_documents = app.doorstop_data.get_documents()
    original_scheduled = list(app.doorstop_data.file_watcher.scheduled_docs)
    candidate_root = tmp_path / "broken-project"
    candidate_root.mkdir()

    def fail_build(*args: object, **kwargs: object) -> doorstop.Tree:
        raise doorstop.DoorstopError("unreadable project configuration")

    monkeypatch.setattr(doorstop, "build", fail_build)
    with pytest.raises(doorstop.DoorstopError, match="unreadable project"):
        app.doorstop_data.rebuild(new_root=candidate_root)

    assert app.doorstop_data.root == original_root
    assert app.doorstop_data._tree is original_tree
    assert app.doorstop_data.get_documents() == original_documents
    assert app.doorstop_data.file_watcher.scheduled_docs == original_scheduled


def test_watcher_retarget_failure_rolls_back_project_and_schedule(
    tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = app.doorstop_data
    original_root = data.root
    original_tree = data._tree
    original_errors = data._item_load_errors
    original_docs = list(data.file_watcher.scheduled_docs)
    candidate_root = tmp_path / "watcher-failure"
    candidate_root.mkdir()
    generate_tree(candidate_root, 1, 2)
    original_watch = data.file_watcher.watch
    scheduled_paths: list[str] = []
    original_schedule = data.file_watcher.observer.schedule

    def record_schedule(*args: Any, **kwargs: Any) -> Any:
        scheduled_paths.append(str(args[1]))
        return original_schedule(*cast(Any, args), **cast(Any, kwargs))

    monkeypatch.setattr(data.file_watcher.observer, "schedule", record_schedule)

    def fail_candidate_watch(docs: list[doorstop.Document]) -> None:
        if docs and Path(docs[0].path).is_relative_to(candidate_root):
            raise RuntimeError("watch scheduling failed")
        original_watch(docs)

    monkeypatch.setattr(data.file_watcher, "watch", fail_candidate_watch)
    with pytest.raises(RuntimeError, match="watch scheduling failed"):
        data.rebuild(new_root=candidate_root)

    assert data.root == original_root
    assert data._tree is original_tree
    assert data._item_load_errors is original_errors
    assert data.file_watcher.scheduled_docs == original_docs
    # This application fixture stops the observer; rollback must not schedule the
    # candidate project, and the prior scheduled document set must be preserved.
    assert all(not Path(path).is_relative_to(candidate_root) for path in scheduled_paths)


def test_validation_menu_action_requests_validation(qtbot: QtBot, app: DoorstopEdit) -> None:
    with patch.object(app, "_request_validation") as request_validation:
        app.window.ui.menu_action_validate_project.trigger()
    request_validation.assert_called_once_with()


def test_validation_completion_rejects_missing_or_invalid_result(
    qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wait_for_validation_idle(qtbot, app)
    monkeypatch.setattr(app.validation_service, "_emit_result", lambda _result: None)
    current = [ValidationFinding("warning", "Keep this finding", "REQ-A-001")]
    app._on_validation_run_result(_run_result(app, current))
    app._on_validation_run_result(
        _run_result(app, (), state="failed", error="Validation helper returned no valid result")
    )
    assert app.validation_status.text() == "Validation could not complete"
    assert "no valid result" in app.validation_dialog.toPlainText()
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None and "Keep this finding" in row.toolTip(1)


def test_stale_validation_result_does_not_replace_current_findings(
    qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wait_for_validation_idle(qtbot, app)
    monkeypatch.setattr(app.validation_service, "_emit_result", lambda _result: None)
    current = _run_result(app, [ValidationFinding("warning", "Current warning", "REQ-A-001")])
    app._on_validation_run_result(current)
    old_status = app.validation_status.text()
    stale = ValidationRunResult(
        current.root,
        current.revision - 1,
        "stale-run",
        (ValidationFinding("error", "Stale error", "REQ-A-002"),),
        "succeeded",
        current.started_at,
        current.completed_at,
        None,
        current.project_id,
    )
    app._on_validation_run_result(stale)
    assert app.validation_status.text() == old_status
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None and "Current warning" in row.toolTip(1)
    app.window.ui.item_tree_search_input.setText("REQ-A-002")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None and "Stale error" not in row.toolTip(1)


def test_project_switch_clears_old_validation_findings(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    _wait_for_validation_idle(qtbot, app)
    app._on_validation_run_result(_run_result(app, [ValidationFinding("error", "Old project error", "REQ-A-001")]))
    new_root = tmp_path / "new-project"
    new_root.mkdir()
    generate_tree(new_root, 1, 2)
    app._rebuild_root(new_root=new_root)
    assert "Old project error" not in app.validation_dialog.toPlainText()
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None and "Old project error" not in row.toolTip(1)

import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import doorstop
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from doorstop_edit.application import DoorstopEdit, QFileDialog
from doorstop_edit.conftest import NUM_DOC
from doorstop_edit.dialogs import ConfirmDialog, InfoDialog
from doorstop_edit.document_dialog import AddDocumentDialog
from doorstop_edit.doorstop_data import ValidationFinding
from doorstop_edit.ui_gen.ui_main import Ui_MainWindow
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


def test_validation_action_and_tree_feedback(qtbot: QtBot, app: DoorstopEdit) -> None:
    app.window.ui.item_tree_search_input.clear()
    app.window.ui.tree_combo_box.setCurrentIndex(0)
    qtbot.waitUntil(lambda: not app._validation_running)
    result = [
        ValidationFinding("error", "REQ-A: REQ-A-001: broken link", "REQ-A-001"),
        ValidationFinding("warning", "REQ-A: REQ-A-002: no text", "REQ-A-002"),
    ]
    app._on_validation_result(app._validation_revision, result, None)

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
    qtbot.waitUntil(lambda: not app._validation_running)
    with patch.object(app, "_start_validation") as start:
        app._validation_running = True
        try:
            app._validation_requested = False
            app._request_validation()
            app._request_validation()
            assert app._validation_requested is True
            assert start.call_count == 0
        finally:
            app._validation_running = False
            app._validation_requested = False


def test_successful_item_save_requests_validation(qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    app.doorstop_data.save_item(item)
    qtbot.waitUntil(lambda: not app._validation_running)
    assert app.validation_status.text().startswith("Validation ·")


def test_validation_failure_keeps_existing_markers(qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    existing = [ValidationFinding("warning", "Existing warning", "REQ-A-001")]
    app._on_validation_result(app._validation_revision, existing, None)
    app._on_validation_result(app._validation_revision, None, "Invalid item")
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
        assert dialog.parent_combo.itemText(0) == "None — top-level"
        dialog.prefix_edit.setText("CHILD")
        qtbot.keyClick(dialog.prefix_edit, Qt.Key.Key_Return)

    QTimer.singleShot(0, fill_dialog)
    qtbot.mouseClick(app.window.ui.edit_document_button, Qt.MouseButton.LeftButton)
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
    qtbot.mouseClick(app.window.ui.edit_document_button, Qt.MouseButton.LeftButton)
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
    qtbot.mouseClick(app.window.ui.edit_document_button, Qt.MouseButton.LeftButton)
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
    qtbot.mouseClick(app.window.ui.toolButton_2, Qt.MouseButton.LeftButton)
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
        qtbot.mouseClick(app.window.ui.toolButton_2, Qt.MouseButton.LeftButton)
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
    assert not app.window.ui.toolButton_2.isEnabled()
    combo.setCurrentIndex(combo.findData("REQ-A"))

    def cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        dialog.defaultButton().click()

    QTimer.singleShot(0, cancel)
    qtbot.mouseClick(app.window.ui.toolButton_2, Qt.MouseButton.LeftButton)
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
    qtbot.mouseClick(app.window.ui.toolButton_2, Qt.MouseButton.LeftButton)
    assert not error_messages, error_messages
    assert app.window.ui.tree_combo_box.count() == 0
    assert app.selected_document is None
    assert not app.window.ui.toolButton_2.isEnabled()
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 0
    assert app.window.ui.item_edit_uid.text() == ""
    assert app.window.ui.edit_document_button.isEnabled()


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
        qtbot.mouseClick(app.window.ui.toolButton_2, Qt.MouseButton.LeftButton)
    assert "Permission denied" in messages[0]
    assert "Check the project" in messages[0]
    assert app.doorstop_data.find_document("REQ-A") is not None


def test_validation_temp_is_retained_while_process_runs(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    result_dir = tmp_path / "validation-result"
    result_dir.mkdir()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    app._validation_process = process
    app._validation_temp = result_dir

    app._cleanup_validation_result()

    assert result_dir.exists()
    process.kill()
    process.wait(timeout=3)
    app._validation_process = None
    app._cleanup_validation_result()


def test_validation_result_error_uses_finished_job_revision(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    result_dir = tmp_path / "validation-result"
    result_dir.mkdir()
    job_revision = app._validation_revision
    app._validation_revision += 1
    app._validation_running = True
    app._validation_result_received = False
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=3)
    app._validation_process = process
    app._validation_job = ("job", tmp_path, job_revision, result_dir / "missing-result.json")
    app._validation_temp = result_dir
    app._validation_requested = False
    prior_status = app.validation_status.text()
    app._process_validation_completion(process, 0)

    assert app.validation_status.text() == prior_status
    assert getattr(app, "_validation_process") is None


def test_quit_retains_result_when_bounded_wait_reports_timeout(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    result_dir = tmp_path / "validation-result"
    result_dir.mkdir()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    app._validation_process = process
    app._validation_temp = result_dir
    reaper_release = threading.Event()
    original_wait = process.wait
    wait_calls = 0

    def wait_with_controlled_timeout(timeout: float = 0.5) -> int:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise subprocess.TimeoutExpired(process.args, timeout)
        if not reaper_release.wait(timeout=3):
            raise RuntimeError("test did not release validator reaper")
        return original_wait(timeout=timeout)

    with (
        patch.object(process, "wait", side_effect=wait_with_controlled_timeout),
        patch.object(app.item_render_view, "destroy"),
        patch.object(app.window, "close"),
    ):
        app.quit()

    assert result_dir.exists()
    assert getattr(app, "_validation_process") is None
    reaper_release.set()
    qtbot.waitUntil(lambda: not result_dir.exists(), timeout=4000)
    assert process.poll() is not None


def test_quit_marks_shutdown_before_stopping_watcher(qtbot: QtBot, app: DoorstopEdit) -> None:
    original_stop = app.doorstop_data.stop
    observed: list[bool] = []

    def stop_watcher() -> None:
        observed.append(app._shutting_down)
        original_stop()

    with (
        patch.object(app.doorstop_data, "stop", side_effect=stop_watcher),
        patch.object(app.item_render_view, "destroy"),
        patch.object(app.window, "close"),
    ):
        app.quit()

    assert observed == [True]

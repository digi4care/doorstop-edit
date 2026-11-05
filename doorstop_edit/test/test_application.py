import json
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional, cast
from unittest.mock import Mock, patch

import doorstop
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from doorstop_edit import application as application_module
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
    app.doorstop_data.stop()  # Application behavior tests do not exercise the file watcher.
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


def test_add_document_creates_and_selects_new_document(
    qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_validation_revision = app._validation_revision

    class AcceptedDialog:
        created_prefix = "NEW"

        def __init__(
            self,
            parent: object,
            prefixes: object,
            selected_prefix: object,
            callback: object,
            *,
            allow_top_level: bool,
        ) -> None:
            assert "REQ-A" in prefixes  # type: ignore[operator]
            assert selected_prefix == "REQ-A"
            assert allow_top_level is False
            callback("NEW", "REQ-A")  # type: ignore[operator]

        def exec(self) -> int:
            return application_module.QDialog.DialogCode.Accepted

    monkeypatch.setattr(application_module, "AddDocumentDialog", AcceptedDialog)
    app._on_add_document_clicked()
    assert app.window.ui.tree_combo_box.currentData() == "NEW"
    assert app.selected_document is not None and app.selected_document.prefix == "NEW"
    assert app.window.ui.remove_document_button.isEnabled()
    assert app._validation_revision > previous_validation_revision
    app.doorstop_data.remove_document("NEW")


def test_add_dialog_allows_top_level_document_in_empty_project(
    qtbot: QtBot, tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(InfoDialog, "inform", lambda *_: None)
    app._rebuild_root(new_root=tmp_path)
    values: list[bool] = []

    class CancelledDialog:
        created_prefix = None

        def __init__(self, *_args: object, allow_top_level: bool) -> None:
            values.append(allow_top_level)

        def exec(self) -> int:
            return application_module.QDialog.DialogCode.Rejected

    monkeypatch.setattr(application_module, "AddDocumentDialog", CancelledDialog)
    app._on_add_document_clicked()
    assert values == [True]


def test_add_dialog_keeps_invalid_prefix_open_and_accepts_callback(qtbot: QtBot, app: DoorstopEdit) -> None:
    calls: list[tuple[str, Optional[str]]] = []

    def create(prefix: str, parent: Optional[str]) -> str:
        calls.append((prefix, parent))
        if "/" in prefix:
            raise doorstop.DoorstopError("Invalid document prefix")
        return prefix

    dialog = AddDocumentDialog(app.window, ["REQ-A"], "REQ-A", create)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.prefix_edit.setText("BAD/NAME")
    dialog.create_button.click()
    assert dialog.isVisible()
    assert "Invalid" in dialog.error_label.text()
    assert calls == [("BAD/NAME", "REQ-A")]
    dialog.prefix_edit.setText("GOOD")
    dialog.create_button.click()
    assert dialog.created_prefix == "GOOD"
    assert dialog.result() == application_module.QDialog.DialogCode.Accepted


def test_remove_parent_refuses_before_confirmation_and_cancel_keeps_leaf(
    qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.doorstop_data.create_document("TEMP", parent="REQ-A")
    notices: list[str] = []
    monkeypatch.setattr(InfoDialog, "inform", lambda _parent, _title, text: notices.append(text))
    monkeypatch.setattr(ConfirmDialog, "ask", lambda *_: pytest.fail("must not confirm parent"))
    app._on_remove_document_clicked()
    assert notices and "TEMP" in notices[0]

    leaf_index = app.window.ui.tree_combo_box.findData("TEMP")
    app.window.ui.tree_combo_box.setCurrentIndex(leaf_index)
    monkeypatch.setattr(ConfirmDialog, "ask", lambda *_: False)
    app._on_remove_document_clicked()
    assert app.doorstop_data.find_document("TEMP") is not None
    app.doorstop_data.remove_document("TEMP")


def test_remove_confirmed_leaf_refreshes_selector_and_empty_editor(
    qtbot: QtBot, tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_tree(tmp_path, 1, 1)
    app._rebuild_root(new_root=tmp_path)
    # The sample generator includes non-document image assets; this scenario
    # targets selector/editor refresh rather than the unmanaged-content guard.
    import shutil

    shutil.rmtree(tmp_path / "REQ-A" / "images", ignore_errors=True)
    leaf = app.doorstop_data.create_document("ONLY", parent="REQ-A")
    app.window.ui.tree_combo_box.setCurrentIndex(app.window.ui.tree_combo_box.findData(leaf))
    monkeypatch.setattr(ConfirmDialog, "ask", lambda *_: True)
    with patch.object(application_module.QMessageBox, "warning") as warning:
        app._on_remove_document_clicked()
    warning.assert_not_called()
    assert app.selected_document is not None and app.selected_document.prefix == "REQ-A"
    assert app.window.ui.tree_combo_box.findData("ONLY") == -1
    assert app.window.ui.item_edit_uid.text() == ""


def test_remove_last_document_leaves_empty_selection(
    qtbot: QtBot, tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_tree(tmp_path, 1, 1)
    import shutil

    shutil.rmtree(tmp_path / "REQ-A" / "images", ignore_errors=True)
    app._rebuild_root(new_root=tmp_path)
    monkeypatch.setattr(ConfirmDialog, "ask", lambda *_: True)
    app._on_remove_document_clicked()
    assert app.window.ui.tree_combo_box.count() == 0
    assert app.selected_document is None
    assert not app.window.ui.remove_document_button.isEnabled()
    assert app.window.ui.item_tree_widget.topLevelItemCount() == 0
    assert app.window.ui.item_edit_uid.text() == ""


def test_remove_backend_failure_reports_partial_state(
    qtbot: QtBot, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaf_prefix = "REQ-C"
    assert app.doorstop_data.find_document(leaf_prefix) is not None
    app.window.ui.tree_combo_box.setCurrentIndex(app.window.ui.tree_combo_box.findData(leaf_prefix))
    monkeypatch.setattr(
        InfoDialog,
        "inform",
        lambda *_: pytest.fail("Unexpected child-document refusal for a leaf"),
    )
    monkeypatch.setattr(ConfirmDialog, "ask", lambda *_: True)
    messages: list[str] = []
    monkeypatch.setattr(application_module.QMessageBox, "warning", lambda _parent, _title, text: messages.append(text))

    def fail_remove(_prefix: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(app.doorstop_data, "remove_document", fail_remove)
    app._on_remove_document_clicked()
    assert "disk full" in messages[0]


def test_remove_refresh_failure_warns_and_disables_stale_editor(
    qtbot: QtBot, tmp_path: Path, app: DoorstopEdit, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    generate_tree(tmp_path, 1, 1)
    shutil.rmtree(tmp_path / "REQ-A" / "images", ignore_errors=True)
    app._rebuild_root(new_root=tmp_path)
    monkeypatch.setattr(ConfirmDialog, "ask", lambda *_: True)
    messages: list[str] = []
    monkeypatch.setattr(application_module.QMessageBox, "warning", lambda _parent, _title, text: messages.append(text))

    def fail_rebuild(*_args: object, **_kwargs: object) -> None:
        raise doorstop.DoorstopError("simulated reload failure")

    real_rebuild = app.doorstop_data.rebuild
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

    monkeypatch.setattr(app.doorstop_data, "rebuild", real_rebuild)
    monkeypatch.setattr(InfoDialog, "inform", lambda *_: None)
    app._rebuild_root(new_root=tmp_path)
    assert not app.doorstop_data.tree_stale


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
        app.doorstop_data.rebuild(new_root=tree_root)


def test_validation_menu_action_requests_validation(qtbot: QtBot, app: DoorstopEdit) -> None:
    with patch.object(app, "_request_validation") as request_validation:
        app.window.ui.menu_action_validate_project.trigger()
    request_validation.assert_called_once_with()


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
        app._validation_requested = False
        app._request_validation()
        app._request_validation()
        app._request_validation()
        assert app._validation_requested is True
        assert start.call_count == 0

        app._finish_validation_process()

        start.assert_called_once_with()


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


@pytest.mark.parametrize("result_content", [None, "not json", json.dumps({"job_id": "wrong"})])
def test_validation_completion_rejects_missing_or_invalid_result(
    tmp_path: Path, qtbot: QtBot, app: DoorstopEdit, result_content: str | None
) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    revision = app._validation_revision
    app._on_validation_result(revision, [ValidationFinding("warning", "Keep this finding", "REQ-A-001")], None)

    result_directory = tmp_path / "validation-result"
    result_directory.mkdir()
    result_path = result_directory / "result.json"
    if result_content is not None:
        result_path.write_text(result_content, encoding="utf-8")
    process = Mock()
    app._validation_process = process
    root = app.doorstop_data.root
    assert root is not None
    app._validation_job = ("expected-job", root.resolve(), revision, result_path)
    app._validation_temp = result_directory
    app._validation_running = True

    app._process_validation_completion(process, 0)

    assert app.validation_status.text() == "Validation could not complete"
    assert "could not complete" in app.validation_dialog.toPlainText()
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None and "Keep this finding" in row.toolTip(1)
    assert not result_directory.exists()


def test_stale_validation_result_does_not_replace_current_findings(qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    current_revision = app._validation_revision
    current = [ValidationFinding("warning", "Current warning", "REQ-A-001")]
    stale = [ValidationFinding("error", "Stale error", "REQ-A-002")]
    app._on_validation_result(current_revision, current, None)
    current_status = app.validation_status.text()

    app._on_validation_result(current_revision - 1, stale, None)

    assert app.validation_status.text() == current_status
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    current_row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert current_row is not None and "Current warning" in current_row.toolTip(1)
    app.window.ui.item_tree_search_input.setText("REQ-A-002")
    stale_row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert stale_row is not None and "Stale error" not in stale_row.toolTip(1)


def test_project_switch_clears_old_validation_findings(tmp_path: Path, qtbot: QtBot, app: DoorstopEdit) -> None:
    qtbot.waitUntil(lambda: not app._validation_running)
    app._on_validation_result(
        app._validation_revision, [ValidationFinding("error", "Old project error", "REQ-A-001")], None
    )
    new_root = tmp_path / "new-project"
    new_root.mkdir()
    generate_tree(new_root, 1, 2)

    app._rebuild_root(new_root=new_root)

    assert "Old project error" not in app.validation_dialog.toPlainText()
    app.window.ui.item_tree_search_input.setText("REQ-A-001")
    row = app.window.ui.item_tree_widget.topLevelItem(0)
    assert row is not None and "Old project error" not in row.toolTip(1)


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


def test_external_valid_to_invalid_item_clears_editor_and_blocks_save(qtbot: QtBot, app: DoorstopEdit) -> None:
    item = app.doorstop_data.find_item("REQ-A-001")
    assert item is not None
    path = Path(item.path)
    valid_contents = path.read_text(encoding="utf-8")
    app.item_edit_view.update_item(item)

    path.write_text("level: bad\n", encoding="utf-8")
    app.doorstop_data._on_filewatch_callback(True, str(path))

    assert app.doorstop_data.get_item_load_error("REQ-A-001")
    assert app.item_edit_view.item is None
    with pytest.raises(ValueError, match="Cannot save invalid item"):
        app.doorstop_data.save_item(item)
    assert path.read_text(encoding="utf-8") == "level: bad\n"

    path.write_text(valid_contents, encoding="utf-8")
    app.doorstop_data._on_filewatch_callback(True, str(path))
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
        app.doorstop_data._on_filewatch_callback(True, str(path))


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
    original_errors = data.item_load_errors
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
    assert data.item_load_errors is original_errors
    assert data.file_watcher.scheduled_docs == original_docs
    assert sorted(scheduled_paths) == sorted(str(Path(doc.path)) for doc in original_docs)

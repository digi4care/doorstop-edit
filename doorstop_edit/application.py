import functools
import html
import logging
from pathlib import Path
from typing import Optional

import doorstop
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from doorstop_edit import crash_log
from doorstop_edit.app_signals import AppSignals
from doorstop_edit.dialogs import ConfirmDialog, InfoDialog, SettingDialog
from doorstop_edit.document_dialog import AddDocumentDialog
from doorstop_edit.doorstop_data import (
    DocumentRemovalRefreshError,
    DoorstopData,
)
from doorstop_edit.item_edit.item_edit_view import ItemEditView
from doorstop_edit.item_render.item_render_view import ItemRenderView
from doorstop_edit.item_tree.item_tree_view import ItemTreeView
from doorstop_edit.main_window import MainWindow
from doorstop_edit.pinned_items.pinned_items_view import PinnedItemsView
from doorstop_edit.settings import PersistentSetting
from doorstop_edit.theme import Theme
from doorstop_edit.ui_gen.ui_item_viewer import Ui_ItemViewer
from doorstop_edit.utils.version_summary import create_version_summary
from doorstop_edit.validation_service import ValidationRunResult, ValidationService

logger = logging.getLogger("gui")


class DoorstopEdit(AppSignals):
    class Settings(PersistentSetting):
        IN_GROUP = "DoorstopEdit"
        last_open_folder = ""

    def __init__(self, root: Optional[Path]) -> None:
        self.window = MainWindow()
        super().__init__(self.window)
        self.window_tile = self.window.windowTitle()
        self.settings = self.Settings()

        if root is None and len(self.settings.last_open_folder) > 0:
            last_open_folder = Path(self.settings.last_open_folder)
            if last_open_folder.is_dir():
                root = last_open_folder

        self.doorstop_data = DoorstopData(self.window, root)
        self.doorstop_data.tree_changed.connect(self._on_tree_changed)
        self.doorstop_data.contentChanged.connect(self._on_content_changed)
        self.validation_service = ValidationService(self.window)
        self.validation_service.result.connect(self._on_validation_run_result)
        self._validation_running = False
        self._validation_revision = self.doorstop_data.content_revision
        self._validation_root: Optional[Path] = None
        self._shutting_down = False
        self.validation_action = self.window.ui.menu_action_validate_project
        self.validation_action.setToolTip("Check all documents and items")
        self.validation_action.triggered.connect(self._request_validation)
        self.validation_status = self.window.ui.validation_status
        self.validation_status.setText("Validation not run")
        self.validation_status.setToolTip("Open project validation results")
        self.validation_dialog = QPlainTextEdit()
        self.validation_dialog.setReadOnly(True)
        self.validation_results_dialog = QDialog(self.window)
        self.validation_results_dialog.setWindowTitle("Project validation")
        self.validation_results_dialog.resize(620, 420)
        layout = QVBoxLayout(self.validation_results_dialog)
        layout.addWidget(self.validation_dialog)
        self.validation_status.clicked.connect(self.validation_results_dialog.show)
        self.setting_dialog = SettingDialog(self.window)
        self.setting_dialog.on_theme_changed.connect(lambda window=self.window: window.update_theme())

        self.window.ui.menu_action_open_folder.triggered.connect(self._open_folder_picker)
        self.window.ui.menu_action_settings.triggered.connect(self._open_settings_dialog)
        self.window.ui.menu_action_exit.triggered.connect(QApplication.exit)
        self.window.ui.item_tree_dock_widget.visibilityChanged.connect(self._dock_item_tree_visibility_changed)
        self.window.ui.menu_action_show_document_tree.triggered[bool].connect(  # type: ignore
            lambda checked, dock=self.window.ui.item_tree_dock_widget: self._on_toggle_dock_widget(checked, dock)
        )
        self.window.ui.edit_item_dock_widget.visibilityChanged.connect(self._dock_item_edit_visibility_changed)
        self.window.ui.menu_action_show_item_editor.triggered[bool].connect(  # type: ignore
            lambda checked, dock=self.window.ui.edit_item_dock_widget: self._on_toggle_dock_widget(checked, dock)
        )
        self.window.ui.pinned_items_dock_widget.visibilityChanged.connect(self._dock_pinned_items_visibility_changed)
        self.window.ui.menu_action_show_pinned_items.triggered[bool].connect(  # type: ignore
            lambda checked, dock=self.window.ui.pinned_items_dock_widget: self._on_toggle_dock_widget(checked, dock)
        )
        self.window.ui.menu_action_about.triggered[bool].connect(  # type: ignore
            lambda checked=False: self._on_about_clicked()
        )
        self.item_render_view = ItemRenderView(self.window.ui.web_engine_view, self.doorstop_data)
        self.item_render_view.on_open_viewer = self._popup_item_viewer
        self.item_render_view.render_progress.connect(self._update_render_progress)

        self.tree_view = ItemTreeView(
            self,
            self.window.ui.item_tree_widget,
            self.window.ui.item_tree_search_input,
            self.doorstop_data,
        )
        self.pinned_items_view = PinnedItemsView(self, self.doorstop_data, self.window.ui.pinned_items_list)
        self.item_edit_view = ItemEditView(self, self.window.ui, self.doorstop_data)
        self.window.ui.tree_combo_box.currentIndexChanged.connect(self._on_selected_document_change)
        self.window.ui.add_document_button.clicked.connect(self._on_add_document_clicked)
        self.window.ui.remove_document_button.clicked.connect(self._on_remove_document_clicked)
        self.window.ui.remove_document_button.setEnabled(False)
        self.window.ui.add_document_button.setEnabled(self.doorstop_data.has_root())
        self._suppress_empty_notice = False
        self._tree_stale = False
        self.window.ui.view_items_mode.currentTextChanged.connect(self._on_view_mode_changed)
        self.window.ui.doc_review_tool_button.clicked.connect(self._on_doc_review_all_button_clicked)
        self.window.ui.doc_clear_links_tool_button.clicked.connect(self._on_doc_clear_all_links_button_clicked)
        self.window.ui.doc_reorder_level_tool_button.clicked.connect(self._on_doc_reoder_all_button_clicked)
        self.window.ui.renderer_search_box.textChanged.connect(self._on_renderer_search_box_text_changed)
        self.window.ui.renderer_search_box.returnPressed.connect(self._on_renderer_search_box_return_pressed)
        self.selected_document: Optional[doorstop.Document] = None
        # Adjust docks width to a sane default (designer seem to not support it).
        self.window.resizeDocks(
            [self.window.ui.item_tree_dock_widget, self.window.ui.edit_item_dock_widget],
            [500, 800],
            Qt.Orientation.Horizontal,
        )

        self.view_item.connect(self._on_view_item)
        self.add_item.connect(self._on_add_item)
        self.add_pin.connect(self.pinned_items_view.add)
        self.item_changed.connect(self._on_item_changed)

        self.item_render_view.show(None)  # Set empty but with correct colors (css).

    def start(self) -> None:
        self.window.show()

        self._dock_item_tree_visibility_changed(self.window.ui.item_tree_dock_widget.isVisible())
        self._dock_item_edit_visibility_changed(self.window.ui.edit_item_dock_widget.isVisible())
        self._dock_pinned_items_visibility_changed(self.window.ui.pinned_items_dock_widget.isVisible())

        # Will trigger view updates.
        self._rebuild_root()
        self.doorstop_data.start()

    def quit(self) -> None:
        """Tear down resources that needs to be teared down before exit."""
        crash_log.record("application.shutdown.begin")
        logger.debug("Quitting...")
        self._shutting_down = True
        self._validation_running = False
        self.doorstop_data.stop()
        self.validation_service.shutdown()
        self.item_render_view.destroy()
        self.window.close()
        crash_log.record("application.shutdown.end")

    def _update_document_list(self) -> None:
        combo = self.window.ui.tree_combo_box
        previous_prefix = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for i, (name, doc) in enumerate(self.doorstop_data.get_documents().items()):
            parent = self.doorstop_data.find_document(doc.parent)
            if parent is None:
                parent_text = ""
            else:
                parent_text = f" (-> {parent.prefix})"
            text = name + parent_text
            combo.addItem(text, name)
            combo.setItemData(i, doc.path, Qt.ItemDataRole.ToolTipRole)
        index = combo.findData(previous_prefix)
        combo.setCurrentIndex(index if index >= 0 else (0 if combo.count() else -1))
        combo.blockSignals(False)
        self._on_selected_document_change(combo.currentIndex())

    def _update_item_tree(self, document: Optional[doorstop.Document]) -> None:
        self.tree_view.update(document.prefix if document else None)

    def _update_used_document(self, document: Optional[doorstop.Document]) -> None:
        """Reload or change used/selected document."""
        old_prefix = self.selected_document.prefix if self.selected_document else None
        self.selected_document = document
        self.window.ui.remove_document_button.setEnabled(document is not None)
        if old_prefix != (document.prefix if document else None):
            self.item_edit_view.update_item(None)
            self.item_render_view.show(None)
        self._update_item_tree(document)

    def _open_item_in_current_document(self, item_uid: str) -> None:
        if not self.selected_document:
            return

        logger.debug("Open item with uid %s", item_uid)

        try:
            item = self.doorstop_data.find_item(item_uid, self.selected_document)
            if item is None:
                return
            item.load(reload=True)  # In case change on disk.
            self.item_render_view.show(item)
            self.item_edit_view.update_item(item)
        except doorstop.DoorstopError as e:
            logger.error(e)
            return

    @Slot(int)
    def _on_selected_document_change(self, index: int) -> None:
        if index == -1:
            self.window.ui.tree_combo_box.setToolTip("")
            self._update_used_document(None)
            return

        doc_uid = self.window.ui.tree_combo_box.itemData(index)
        # Copy tooltip from entry to main widget.
        self.window.ui.tree_combo_box.setToolTip(
            self.window.ui.tree_combo_box.itemData(index, Qt.ItemDataRole.ToolTipRole)
        )

        logger.debug("Selected document changed to %s", doc_uid)

        doc = self.doorstop_data.find_document(doc_uid)
        if doc is None:
            self._update_used_document(None)
            return

        self._update_used_document(doc)

    def _on_add_document_clicked(self) -> None:
        if not self.doorstop_data.has_root():
            return
        dialog = AddDocumentDialog(
            self.window,
            self.doorstop_data.get_documents(),
            self.selected_document.prefix if self.selected_document else None,
            self.doorstop_data.create_document,
            allow_top_level=not any(doc.parent is None for doc in self.doorstop_data.get_documents().values()),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_prefix is not None:
            index = self.window.ui.tree_combo_box.findData(dialog.created_prefix)
            if index >= 0:
                self.window.ui.tree_combo_box.setCurrentIndex(index)

    def _on_remove_document_clicked(self) -> None:
        if self.selected_document is None:
            return
        prefix = self.selected_document.prefix
        documents = self.doorstop_data.get_documents()
        children = sorted(doc.prefix for doc in documents.values() if doc.parent == prefix)
        if children:
            InfoDialog.inform(
                self.window,
                "Cannot remove document",
                "Remove the child documents first: " + ", ".join(html.escape(child) for child in children),
            )
            return

        confirmation = QMessageBox(self.window)
        confirmation.setWindowTitle("Remove document")
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setText(f"Remove document {prefix} and its items? This cannot be undone.")
        cancel = confirmation.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        confirmation.addButton("Remove document", QMessageBox.ButtonRole.DestructiveRole)
        confirmation.setDefaultButton(cancel)
        confirmation.exec()
        clicked = confirmation.clickedButton()
        if clicked is None or confirmation.buttonRole(clicked) != QMessageBox.ButtonRole.DestructiveRole:
            return
        self._suppress_empty_notice = True
        try:
            self.doorstop_data.remove_document(prefix)
        except DocumentRemovalRefreshError as exc:
            self._mark_document_tree_stale()
            QMessageBox.warning(
                self.window,
                "Document deletion may be partial",
                f"{exc}\nThe displayed document tree may be stale. Reopen or reload the project before editing.",
            )
        except (doorstop.DoorstopError, OSError) as exc:
            message = QMessageBox(self.window)
            message.setWindowTitle("Could not remove document")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText(f"Could not remove document {prefix}: {exc}\nCheck the project before trying again.")
            message.exec()
        finally:
            self._suppress_empty_notice = False

    def _mark_document_tree_stale(self) -> None:
        self._tree_stale = True
        self.window.ui.tree_combo_box.setEnabled(False)
        self.window.ui.add_document_button.setEnabled(False)
        self.window.ui.remove_document_button.setEnabled(False)
        self.item_edit_view.update_item(None)
        self.item_render_view.show(None)
        self._update_item_tree(None)

    def _on_view_mode_changed(self, new_mode: str) -> None:
        if new_mode == "Document":
            self.item_render_view.set_view_mode(ItemRenderView.ViewMode.Document)
        elif new_mode == "Section":
            self.item_render_view.set_view_mode(ItemRenderView.ViewMode.Section)
        elif new_mode == "Item":
            self.item_render_view.set_view_mode(ItemRenderView.ViewMode.Item)

    @Slot(doorstop.Item)
    def _on_item_changed(self, item: doorstop.Item) -> None:
        self.item_render_view.show(item)
        self.tree_view.update_selected_items([item])

    @Slot(str)
    def _on_add_item(self, after_item_uid: Optional[str]) -> None:
        if self.selected_document is None:
            return

        level = None
        if after_item_uid is not None:
            item = self.doorstop_data.find_item(after_item_uid)
            if item is not None:
                try:
                    level = str(item.level)
                    level_last = int(level[-1])
                    level = level[:-1] + str(level_last + 1)
                except Exception:
                    pass

        new_item = self.selected_document.add_item(level=level, reorder=False)
        new_item.header = "New item"
        new_item.normative = True
        new_item.active = True
        self.doorstop_data.save_item(new_item)
        self.tree_view.set_selected_items([new_item])

    def _on_toggle_dock_widget(self, checked: bool, dock: QDockWidget) -> None:
        if checked:
            dock.show()
        else:
            dock.close()

    def _on_about_clicked(self) -> None:
        def on_clicked(text: str) -> bool:
            QGuiApplication.clipboard().setText(text)
            return True

        version_summary = create_version_summary()
        msg = f"""\n
<h3>Doorstop Edit</h3>
<p>
{"".join([f"{x}<br>" for x in version_summary.splitlines()])}
</p>
"""
        InfoDialog.inform(
            self.window,
            "About",
            msg,
            extra_button_name="Copy",
            extra_button_cb=functools.partial(on_clicked, version_summary),
            extra_button_icon=":/icons/copy",
        )

    @Slot(str, bool)
    def _on_view_item(self, item_uid: str, new_window: bool) -> None:
        if new_window:
            self._popup_item_viewer(item_uid)
        else:
            self._open_item_in_current_document(item_uid)

    def _popup_item_viewer(self, item_uid: str) -> None:
        item = self.doorstop_data.find_item(item_uid)
        if item is None:
            return
        ui = Ui_ItemViewer()
        w = QDialog(self.window, Qt.WindowType.Window)
        ui.setupUi(w)
        irv = ItemRenderView(ui.web_engine_view, self.doorstop_data)
        irv.on_open_viewer = self._popup_item_viewer
        irv.show(item)
        w.show()
        w.setWindowTitle(f"[{item.uid}] {item.header}")

    def _on_doc_review_all_button_clicked(self) -> None:
        if not ConfirmDialog.ask(
            self.window,
            """\
Are you sure you want to mark all items as reviewed?

WARNING: This operation cannot be undone!
""",
        ):
            return

        if self.selected_document is None:
            return

        for item in self.doorstop_data.iter_items(self.selected_document):
            item.review()
            self.doorstop_data.save_item(item)

        self.tree_view.update(self.selected_document.prefix)
        self.item_edit_view.update_item(None)

    def _on_doc_clear_all_links_button_clicked(self) -> None:
        if not ConfirmDialog.ask(
            self.window,
            """\
Are you sure you want to clear all suspect links in selected document?

WARNING: This operation cannot be undone!
""",
        ):
            return

        if self.selected_document is None:
            return

        for item in self.doorstop_data.iter_items(self.selected_document):
            item.clear()
            self.doorstop_data.save_item(item)

        self.tree_view.update(self.selected_document.prefix)
        self.item_edit_view.update_item(None)

    def _on_doc_reoder_all_button_clicked(self) -> None:
        if not ConfirmDialog.ask(
            self.window,
            """\
Are you sure you want do an automatic level reorder of of all items in selected document?

WARNING: This operation cannot be undone!
""",
        ):
            return

        if self.selected_document is None:
            return

        self.selected_document.reorder(manual=False)

        for item in self.doorstop_data.iter_items(self.selected_document):
            self.doorstop_data.save_item(item)

        self.tree_view.update(self.selected_document.prefix)
        self.item_edit_view.update_item(None)

    @Slot(bool)
    def _on_tree_changed(self, modified_only: bool) -> None:
        if self._tree_stale:
            return
        if (
            self.doorstop_data.has_root()
            and len(self.doorstop_data.get_documents()) == 0
            and not self._suppress_empty_notice
        ):
            msg = "No doorstop documents found in project root."
            InfoDialog.inform(self.window, "Empty project", msg)

        if not self._tree_stale:
            self.window.ui.tree_combo_box.setEnabled(True)
        if not modified_only:
            self._update_document_list()
        self.window.ui.add_document_button.setEnabled(self.doorstop_data.has_root())
        if self.selected_document:
            self._update_item_tree(self.selected_document)
        self.item_edit_view.reload()

    def _on_content_changed(self, root: str, revision: int, reason: str) -> None:
        del reason
        self._queue_validation(Path(root), revision)

    def _request_validation(self) -> None:
        root = self.doorstop_data.root
        if root is not None:
            self._queue_validation(root, self.doorstop_data.content_revision)

    def _queue_validation(self, root: Optional[Path] = None, revision: Optional[int] = None) -> None:
        if self._shutting_down or not self.doorstop_data.has_root():
            return
        root = root or self.doorstop_data.root
        if root is None:
            return
        revision = self.doorstop_data.content_revision if revision is None else revision
        if self._validation_root != root.resolve():
            self._validation_root = root.resolve()
            self.tree_view.set_validation_findings([])
            self.validation_dialog.setPlainText("Checking the opened project…")
        self._validation_revision = revision
        self._validation_running = True
        self.validation_status.setText("Checking project…")
        self.validation_service.request(root, revision)

    @Slot(object)
    def _on_validation_run_result(self, result: ValidationRunResult) -> None:
        if result.state != "running":
            self._validation_running = False
        if self._shutting_down:
            return
        current_root = self.doorstop_data.root
        if current_root is None or Path(result.root).resolve() != current_root.resolve():
            return
        if result.content_revision != self.doorstop_data.content_revision:
            return
        self._validation_running = result.state == "running"
        self._validation_revision = result.content_revision
        if result.state == "running":
            self.validation_status.setText("Checking project…")
            return
        if result.state == "failed":
            self.validation_status.setText("Validation could not complete")
            self.validation_dialog.setPlainText(f"Project validation could not complete:\n{result.error}")
            return
        findings = list(result.findings)
        self.tree_view.set_validation_findings(findings)
        errors = sum(f.severity == "error" for f in findings)
        warnings = sum(f.severity == "warning" for f in findings)
        info = sum(f.severity == "info" for f in findings)
        self.validation_status.setText(
            f"Validation · {errors} error{'s' if errors != 1 else ''} · "
            f"{warnings} warning{'s' if warnings != 1 else ''} · {info} notice{'s' if info != 1 else ''}"
        )
        self.validation_dialog.setPlainText(
            "\n".join(f"{f.severity.upper()} · {f.item_uid or 'Project'} · {f.message}" for f in findings)
            or "No validation findings."
        )

    @Slot(int)
    def _update_render_progress(self, percentage: int) -> None:
        self.window.ui.render_progress_bar.setMaximum(100)
        self.window.ui.render_progress_bar.setValue(percentage)

    @Slot(str)
    def _on_renderer_search_box_text_changed(self, text: str) -> None:
        self.window.ui.web_engine_view.findText(text)

    @Slot()
    def _on_renderer_search_box_return_pressed(self) -> None:
        self.window.ui.web_engine_view.findText(self.window.ui.renderer_search_box.text())

    def _on_dock_visibility_changed(self, visible: bool, action: QAction) -> None:
        action.setChecked(visible)

    @Slot(bool)
    def _dock_item_tree_visibility_changed(self, visible: bool) -> None:
        self._on_dock_visibility_changed(visible, self.window.ui.menu_action_show_document_tree)

    @Slot(bool)
    def _dock_item_edit_visibility_changed(self, visible: bool) -> None:
        self._on_dock_visibility_changed(visible, self.window.ui.menu_action_show_item_editor)

    @Slot(bool)
    def _dock_pinned_items_visibility_changed(self, visible: bool) -> None:
        self._on_dock_visibility_changed(visible, self.window.ui.menu_action_show_pinned_items)

    @Slot()
    def _open_settings_dialog(self) -> None:
        self.setting_dialog.open()

    @Slot()
    def _open_folder_picker(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.window, "Open Folder")
        if len(folder) > 0:
            self._rebuild_root(new_root=Path(folder))

    def _rebuild_root(self, new_root: Optional[Path] = None) -> None:
        project_changed = new_root is not None and self.doorstop_data.root != new_root
        try:
            if project_changed:
                self.item_edit_view.cancel_pending_save()
                self.item_edit_view.update_item(None)
                self.item_render_view.show(None)
            self.doorstop_data.rebuild(only_reload=False, new_root=new_root)
            self._tree_stale = False
            # Save as last opened if rebuild succeeded. Will be default after next restart.
            self.settings.last_open_folder = str(self.doorstop_data.root)
            if self.doorstop_data.root is not None:
                self.window.setWindowTitle(f"{self.doorstop_data.root.name} - {self.window_tile}")
        except doorstop.DoorstopError as e:
            logger.exception(e)
            InfoDialog.inform(
                self.window,
                title="Error",
                text=f"""\
<p style="font-weight:700;">Failed to open folder:</p>
<p style="font-style:italic;color:{str(Theme.DANGER_COLOR.name())};">{str(e).capitalize()}</p>""",
            )

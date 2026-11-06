from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from doorstop_edit.item_edit.item_picker_dialog import ItemPickerDialog


def test_picker_filters_and_accepts_selected_item(qapp: QApplication, doorstop_data: Mock) -> None:
    selected: list[str] = []
    parent = QWidget()
    dialog = ItemPickerDialog(parent, doorstop_data, selected.append)

    dialog._on_search_input_changed("REQ-A-001")
    results = dialog._dialog.ui.search_result
    assert results.count() == 1
    entry = results.item(0)
    uid = entry.data(Qt.ItemDataRole.UserRole)
    assert uid == "REQ-A-001"
    assert entry.data(Qt.ItemDataRole.ToolTipRole)

    entry.setSelected(True)
    dialog._on_accepted_button_pressed()
    assert selected == [uid]


def test_picker_accept_without_selection_is_noop(qapp: QApplication, doorstop_data: Mock) -> None:
    selected: list[str] = []
    parent = QWidget()
    dialog = ItemPickerDialog(parent, doorstop_data, selected.append)

    dialog._on_accepted_button_pressed()

    assert selected == []

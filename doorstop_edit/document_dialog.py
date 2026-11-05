"""Document creation dialog with inline errors and a selectable parent."""

from typing import Callable, Iterable, Optional

import doorstop
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class AddDocumentDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        prefixes: Iterable[str],
        selected_prefix: Optional[str],
        create_document: Callable[[str, Optional[str]], str],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add document")
        self.setMinimumWidth(360)
        self.created_prefix: Optional[str] = None
        self._create_document = create_document

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.prefix_edit = QLineEdit(self)
        self.prefix_edit.setObjectName("document_prefix")
        self.prefix_edit.setPlaceholderText("e.g. SPEC")
        self.prefix_edit.setAccessibleName("Prefix")
        form.addRow("Prefix", self.prefix_edit)
        self.parent_combo = QComboBox(self)
        self.parent_combo.setObjectName("document_parent")
        self.parent_combo.setAccessibleName("Parent document")
        self.parent_combo.addItem("None — top-level", None)
        for prefix in prefixes:
            self.parent_combo.addItem(prefix, prefix)
        if selected_prefix is not None:
            index = self.parent_combo.findData(selected_prefix)
            if index >= 0:
                self.parent_combo.setCurrentIndex(index)
        form.addRow("Parent document", self.parent_combo)
        layout.addLayout(form)

        self.error_label = QLabel(self)
        self.error_label.setObjectName("document_error")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b33838;")
        self.error_label.setAccessibleName("Document error")
        layout.addWidget(self.error_label)
        self.prefix_edit.textChanged.connect(lambda _: self.error_label.clear())

        buttons = QDialogButtonBox(self)
        self.create_button = buttons.addButton("Add document", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._create)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _create(self) -> None:
        prefix = self.prefix_edit.text()
        if not prefix.strip():
            self.error_label.setText("Prefix is required.")
            self.prefix_edit.setFocus()
            return
        try:
            self.created_prefix = self._create_document(prefix, self.parent_combo.currentData())
        except (doorstop.DoorstopError, OSError) as exc:
            self.error_label.setText(f"Could not add document: {exc}")
            self.prefix_edit.setFocus()
            return
        self.accept()

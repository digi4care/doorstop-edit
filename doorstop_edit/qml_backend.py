import logging
from pathlib import Path
from typing import Optional

import doorstop
from PySide6 import QtCore, QtWidgets

from doorstop_edit.doorstop_data import DoorstopData
from doorstop_edit.settings import PersistentSetting

logger = logging.getLogger("gui")


class QmlBackend(QtCore.QObject):
    projectRootChanged = QtCore.Signal()
    statusMessageChanged = QtCore.Signal()
    errorMessageChanged = QtCore.Signal()
    documentsChanged = QtCore.Signal()
    itemsChanged = QtCore.Signal()
    selectedItemChanged = QtCore.Signal()

    class Settings(PersistentSetting):
        IN_GROUP = "DoorstopEdit"
        last_open_folder = ""

    def __init__(self, parent: Optional[QtCore.QObject] = None, root: Optional[Path] = None) -> None:
        super().__init__(parent)
        self._settings = self.Settings()
        if root is None and self._settings.last_open_folder:
            candidate = Path(self._settings.last_open_folder)
            root = candidate if candidate.is_dir() else None
        self._data = DoorstopData(self, root)
        self._status = ""
        self._error = ""
        self._selected_document = ""
        self._selected_uid = ""
        self._header = ""
        self._level = ""
        self._text = ""
        self._opening_project = False
        self._data.tree_changed.connect(self._tree_changed)
        self._data.item_saved.connect(self._item_saved)
        if root is not None:
            self._rebuild(root)

    @QtCore.Property(str, notify=projectRootChanged)
    def projectRoot(self) -> str:
        return str(self._data.root or "")

    @QtCore.Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:
        return self._status

    @QtCore.Property(str, notify=errorMessageChanged)
    def errorMessage(self) -> str:
        return self._error

    @QtCore.Property(list, notify=documentsChanged)
    def documents(self) -> list:
        return [
            {
                "prefix": name,
                "path": str(doc.path),
                "parent": str(doc.parent or ""),
                "count": sum(1 for _ in doc),
            }
            for name, doc in self._data.get_documents().items()
        ]

    @QtCore.Property(list, notify=itemsChanged)
    def items(self) -> list:
        doc = self._data.find_document(self._selected_document)
        if doc is None:
            return []
        return [
            {
                "uid": str(item.uid),
                "level": str(item.level),
                "header": str(item.header),
                "active": bool(item.active),
                "normative": bool(item.normative),
            }
            for item in self._data.iter_items(doc)
        ]

    @QtCore.Property(dict, notify=selectedItemChanged)
    def selectedItem(self) -> dict:
        return {"uid": self._selected_uid, "level": self._level, "header": self._header, "text": self._text}

    def _message(self, text: str) -> None:
        self._error = text
        self.errorMessageChanged.emit()

    @QtCore.Slot()
    def openProjectPicker(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(None, "Open Doorstop project")
        if path:
            self.openProject(path)

    @QtCore.Slot(str)
    def openProject(self, path: str) -> None:
        if not Path(path).is_dir():
            self._message(f"Invalid project root: {path} is not a directory")
            return
        self._rebuild(Path(path))

    def _rebuild(self, root: Path) -> None:
        previous_root = self._data.root
        self._opening_project = True
        try:
            self._data.rebuild(only_reload=False, new_root=root)
            self._data.start()
            self._selected_document = ""
            self._selected_uid = self._level = self._header = self._text = ""
            self.documentsChanged.emit()
            self.itemsChanged.emit()
            self.selectedItemChanged.emit()
            self._settings.last_open_folder = str(root)
            self._message("")
            self.projectRootChanged.emit()
            self._status = f"Opened {root}"
            self.statusMessageChanged.emit()
        except (doorstop.DoorstopError, OSError) as exc:
            self._data.root = previous_root
            # DoorstopData pauses the watcher before building. A failed build leaves the old tree
            # intact, but its directories must be rescheduled on the existing watcher.
            self._data.file_watcher.watch(list(self._data.get_documents().values()))
            logger.exception("Unable to open project root")
            self._message(str(exc))
        finally:
            self._opening_project = False

    @QtCore.Slot(str)
    def selectDocument(self, prefix: str) -> None:
        self._selected_document = prefix
        self._selected_uid = self._level = self._header = self._text = ""
        self.documentsChanged.emit()
        self.itemsChanged.emit()
        self.selectedItemChanged.emit()

    @QtCore.Slot(str)
    def selectItem(self, uid: str) -> None:
        try:
            item = self._data.find_item(uid, self._selected_document)
            if item is None:
                self._message(f"Unknown item: {uid}")
                return
            item.load(reload=True)
            self._selected_uid, self._level, self._header, self._text = (
                str(item.uid),
                str(item.level),
                str(item.header),
                str(item.text),
            )
            self._message("")
            self.selectedItemChanged.emit()
        except (doorstop.DoorstopError, OSError) as exc:
            self._message(str(exc))

    @QtCore.Slot(str, str)
    def saveSelected(self, header: str, text: str) -> None:
        try:
            item = self._data.find_item(self._selected_uid, self._selected_document)
            if item is None:
                raise doorstop.DoorstopError("No item is selected")
            item.header = header
            item.text = text
            self._data.save_item(item)
            self._level, self._header, self._text = str(item.level), header, text
            self._message("")
            self.selectedItemChanged.emit()
        except (doorstop.DoorstopError, OSError) as exc:
            self._message(str(exc))

    @QtCore.Slot(bool)
    def _tree_changed(self, _modified_only: bool) -> None:
        self.documentsChanged.emit()
        self.itemsChanged.emit()
        if self._selected_uid and not self._opening_project:
            self.selectItem(self._selected_uid)
        self.statusMessageChanged.emit()

    @QtCore.Slot()
    def _item_saved(self) -> None:
        self.itemsChanged.emit()
        self.statusMessageChanged.emit()

    @QtCore.Slot()
    def shutdown(self) -> None:
        self._data.stop()

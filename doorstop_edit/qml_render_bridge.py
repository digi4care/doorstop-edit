"""Qt Quick renderer adapter: DoorstopData -> existing worker -> WebChannel."""

import html
import logging
from pathlib import Path
from typing import cast

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from doorstop_edit.item_render.item_render_view import HTML_TEMPLATE, QML_BRIDGE_READY_MARKER
from doorstop_edit.item_render.markdown_css import MARKDOWN_CSS
from doorstop_edit.item_render.render_worker import RenderWorker
from doorstop_edit.qml_backend import QmlBackend

logger = logging.getLogger("gui")


class QmlRenderBridge(QObject):
    """Keep the WebEngine page and worker output in sync with the current selection."""

    pageChanged = Signal()
    errorChanged = Signal()
    stateChanged = Signal()
    htmlUpdateItem = Signal(str, str, bool, bool)
    htmlSelectItem = Signal(str)
    itemRequested = Signal(str, str)
    popupCreated = Signal(QObject, str)

    def __init__(self, backend: QmlBackend, parent: QObject | None = None, pinned_uid: str = "") -> None:
        super().__init__(parent)
        self.backend = backend
        self._pinned_uid = pinned_uid
        self._popups: list[QmlRenderBridge] = []
        self._worker = RenderWorker(self)
        self._worker.result_tagged.connect(self._on_result)
        self._worker.progress_tagged.connect(self._on_progress)
        self._worker.error_tagged.connect(self._on_error)
        self._worker.finished_tagged.connect(self._on_finished)
        self._error = ""
        self._page_html = ""
        self._base_url = QUrl.fromLocalFile(str(Path.cwd()) + "/")
        self._loaded = False
        self._channel_ready = False
        self._stopped = False
        self._document_path: Path | None = None
        self._project_root = ""
        self._placeholders: tuple[str, ...] = ()
        self._uid = ""
        self._mode = "document"
        self._page_generation = 0
        self._active_job: int | None = None
        self._render_started = False
        self._content: dict[str, str] = {}
        self._progress = 0
        self._running = False
        if not pinned_uid:
            backend.selectedItemChanged.connect(self.refresh)
        backend.projectRootChanged.connect(self.reload)
        backend.itemsChanged.connect(self._items_changed)
        self.refresh()

    @Property(str, notify=pageChanged)
    def pageHtml(self) -> str:
        return self._page_html

    @Property(QUrl, notify=pageChanged)
    def baseUrl(self) -> QUrl:
        return self._base_url

    @Property(str, notify=errorChanged)
    def errorMessage(self) -> str:
        return self._error

    @Property(str, notify=stateChanged)
    def viewMode(self) -> str:
        return self._mode

    @Property(int, notify=stateChanged)
    def progress(self) -> int:
        return self._progress

    @Property(bool, notify=stateChanged)
    def running(self) -> bool:
        return self._running

    def _set_error(self, message: str) -> None:
        if message != self._error:
            self._error = message
            self.errorChanged.emit()

    def _set_state(self, progress: int, running: bool) -> None:
        self._progress = progress
        self._running = running
        self.stateChanged.emit()

    @Slot(str)
    def setViewMode(self, mode: str) -> None:
        if mode not in ("document", "section", "item"):
            return
        if mode != self._mode:
            self._mode = mode
            self.stateChanged.emit()
            self._replay_content()

    @Slot()
    def reload(self) -> None:
        self.refresh(force_reload=True)

    @Slot()
    def refresh(self, force_reload: bool = False) -> None:
        if self._stopped:
            return
        selection = cast(dict[str, object], self.backend.property("selectedItem"))
        uid = self._pinned_uid or str(selection.get("uid") or "")
        item = self.backend._data.find_item(uid) if uid else None
        path = Path(item.document.path) if item is not None else None
        root = cast(str, self.backend.property("projectRoot"))
        rows = (
            sorted(
                self.backend._data.iter_items(item.document),
                key=lambda row: [int(n) for n in str(row.level).split(".")],
            )
            if item is not None
            else []
        )
        placeholders = tuple(row.uid.value for row in rows)
        same_page = (
            not force_reload
            and self._loaded
            and self._channel_ready
            and path is not None
            and path == self._document_path
            and root == self._project_root
            and placeholders == self._placeholders
        )
        self._render_started = False
        was_running = self._running
        self._active_job = None  # queued output from the previous request is no longer valid
        self._uid = uid if item is not None else ""
        self._document_path = path
        self._project_root = root
        self._placeholders = placeholders
        self._set_error("")
        self._set_state(0, bool(item))
        if same_page:
            if self._loaded and self._channel_ready:
                self.htmlSelectItem.emit(self._uid)
                self._replay_content()
                # A superseded job may already have populated the worker cache while
                # its output was discarded. Rebuild fully so no fragment is lost.
                self._start_render(partial=not was_running)
            # If loading, the pending handshake starts a full render for the new selection.
            return

        self._content.clear()
        self._loaded = self._channel_ready = False
        self._page_generation += 1
        body = "".join(
            f'<div id="{html.escape(row.uid.value, quote=True)}" class="doorstop-item"></div>\n' for row in rows
        )
        base_path = path.resolve() if path else Path.cwd()
        self._base_url = QUrl.fromLocalFile(str(base_path) + "/")
        # A page-specific handshake prevents a late callback from a replaced page
        # from starting work against the new selection.
        page_html = HTML_TEMPLATE.format(body=body, style=MARKDOWN_CSS)
        if page_html.count(QML_BRIDGE_READY_MARKER) != 1:
            raise RuntimeError("QML WebChannel readiness marker must appear exactly once")
        self._page_html = page_html.replace(
            QML_BRIDGE_READY_MARKER,
            f"py.bridgeReady({self._page_generation});",
            1,
        )
        self.pageChanged.emit()

    @Slot()
    def _items_changed(self) -> None:
        if self._uid:
            self.refresh()

    @Slot(int)
    def bridgeReady(self, generation: int) -> None:
        if generation == self._page_generation:
            self._channel_ready = True
            self._render_if_ready()

    @Slot()
    def loadSucceeded(self) -> None:
        self._loaded = True
        self._render_if_ready()

    @Slot(str)
    def loadFailed(self, detail: str) -> None:
        self._loaded = False
        self._active_job = None
        self._set_state(self._progress, False)
        self._set_error(f"Preview could not load: {detail or 'unknown WebEngine error'}")

    def _render_if_ready(self) -> None:
        if (
            not self._loaded
            or not self._channel_ready
            or self._active_job is not None
            or not self._uid
            or self._stopped
        ):
            return
        self.htmlSelectItem.emit(self._uid)
        self._start_render(partial=False)

    def _start_render(self, partial: bool) -> None:
        item = self.backend._data.find_item(self._uid)
        if item is None or Path(item.document.path) != self._document_path:
            self._set_state(self._progress, False)
            self._set_error("Preview item is no longer available.")
            return
        items = [item]
        items.extend(row for row in self.backend._data.iter_items(item.document) if row.uid.value != self._uid)
        self._set_state(0, True)
        self._render_started = True
        self._active_job = self._worker.render(
            [(row, self.backend._data.get_last_change(row)) for row in items],
            self._document_path,
            partial=partial,
        )

    def _hidden(self, uid: str) -> bool:
        if uid == "footer" or not self._uid:
            return False
        item = self.backend._data.find_item(uid)
        selected = self.backend._data.find_item(self._uid)
        if item is None or selected is None:
            return True
        if not item.active and uid != self._uid:
            return True
        if self._mode == "item":
            return uid != self._uid
        if self._mode == "section":
            from doorstop_edit.utils.item_utils import match_level

            return not match_level(item, selected.level, include_parent=True)
        return False

    def _replay_content(self) -> None:
        for uid, content in self._content.items():
            self.htmlUpdateItem.emit(uid, content, uid == self._uid, self._hidden(uid))

    @Slot(int, str, str)
    def _on_result(self, job: int, uid: str, content: str) -> None:
        if self._stopped or job != self._active_job or self._document_path is None:
            return
        if uid != "footer":
            item = self.backend._data.find_item(uid)
            if item is None or Path(item.document.path) != self._document_path or uid not in self._placeholders:
                return
        self._content[uid] = content
        self.htmlUpdateItem.emit(uid, content, uid == self._uid, self._hidden(uid))

    @Slot(int, int)
    def _on_progress(self, job: int, value: int) -> None:
        if not self._stopped and job == self._active_job:
            self._set_state(min(100, max(0, value)), True)

    @Slot(int, str)
    def _on_error(self, job: int, detail: str) -> None:
        if not self._stopped and job == self._active_job:
            logger.error("Preview render failed: %s", detail)
            self._set_error(f"Preview could not render: {detail}")
            self._set_state(self._progress, False)

    @Slot(int)
    def _on_finished(self, job: int) -> None:
        if not self._stopped and job == self._active_job:
            self._set_state(100 if not self._error else self._progress, False)

    @Slot(str)
    def open_item(self, uid: str) -> None:
        if self._pinned_uid:
            # A link inside a viewer opens another viewer, as in Widgets.
            self.openPopupItem(uid)
        else:
            # Main.qml confirms unsaved drafts before changing the current editor.
            self.requestItem(uid)

    @Slot(str)
    def openPopupItem(self, uid: str) -> None:
        item = self.backend._data.find_item(uid)
        if item is None:
            self._set_error(f"Preview item not found: {uid}")
            return
        popup = QmlRenderBridge(self.backend, self, pinned_uid=uid)
        self._popups.append(popup)
        self.popupCreated.emit(popup, f"[{uid}] {item.header}")

    @Slot(str)
    def openPopupDocument(self, prefix: str) -> None:
        document = self.backend._data.find_document(prefix)
        if document is None:
            self._set_error(f"Preview document not found: {prefix}")
            return
        item = next(iter(self.backend._data.iter_items(document)), None)
        if item is None:
            self._set_error(f"Preview document has no items: {prefix}")
            return
        self.openPopupItem(item.uid.value)

    @Slot(str)
    def requestItem(self, uid: str) -> None:
        item = self.backend._data.find_item(uid)
        if item is None:
            self._set_error(f"Preview item not found: {uid}")
            return
        # Current-view navigation is confirmed by the shell before changing the draft.
        self.itemRequested.emit(uid, item.document.prefix)

    @Slot(QObject)
    def closePopup(self, popup: QObject) -> None:
        if popup in self._popups:
            self._popups.remove(popup)
            popup.shutdown()
            popup.deleteLater()

    @Slot()
    def dispose(self) -> None:
        owner = self.parent()
        if isinstance(owner, QmlRenderBridge):
            owner.closePopup(self)

    @Slot(str)
    def openExternal(self, address: str) -> None:
        # A clicked link must never replace the trusted preview/WebChannel page.
        url = QUrl(address)
        # Widgets hands every clicked URL to the platform handler. Navigation
        # is rejected separately by the WebEngine view.
        if not QDesktopServices.openUrl(url):
            self._set_error(f"Preview link could not be opened: {address}")

    @Slot()
    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._active_job = None
        for popup in list(self._popups):
            self.closePopup(popup)
        self._worker.destroy()

"""
QML Bridge Module - Connects QML UI to Python backend
Corresponds to bead: doorstop-edit-qml-frontend-migration-plan-lml.2.1
"""

from typing import Any

from PySide6.QtCore import Property, QByteArray, QObject, Signal, Slot
from PySide6.QtQml import qmlRegisterType


class WindowStateManager(QObject):
    """Manages window geometry and dock state for persistence"""

    # Signals emitted when UI state changes
    geometryChanged = Signal()
    stateChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._geometry = QByteArray()
        self._state = QByteArray()
        self._window_width = 1200
        self._window_height = 800

    # Geometry property
    @Property(QByteArray, notify=geometryChanged)
    def geometry(self) -> QByteArray:
        return self._geometry

    @geometry.setter  # type: ignore[no-redef]
    def geometry(self, value: QByteArray) -> None:
        if self._geometry != value:
            self._geometry = value
            self.geometryChanged.emit()

    # State property (dock layout)
    @Property(QByteArray, notify=stateChanged)
    def state(self) -> QByteArray:
        return self._state

    @state.setter  # type: ignore[no-redef]
    def state(self, value: QByteArray) -> None:
        if self._state != value:
            self._state = value
            self.stateChanged.emit()

    # Current window dimensions
    @Property(int, notify=geometryChanged)
    def windowWidth(self) -> int:
        return self._window_width

    @windowWidth.setter  # type: ignore[no-redef]
    def windowWidth(self, width: int) -> None:
        if self._window_width != width:
            self._window_width = width
            self.geometryChanged.emit()

    @Property(int, notify=geometryChanged)
    def windowHeight(self) -> int:
        return self._window_height

    @windowHeight.setter  # type: ignore[no-redef]
    def windowHeight(self, height: int) -> None:
        if self._window_height != height:
            self._window_height = height
            self.geometryChanged.emit()

    @Slot(result=str)
    def saveGeometry(self) -> str:
        """Save current window geometry"""
        print(f"Saving geometry: {self._window_width}x{self._window_height}")
        geometry_bytes = bytes(self._geometry)  # type: ignore[call-overload]
        return geometry_bytes.hex() if geometry_bytes else ""

    @Slot(result=str)
    def saveState(self) -> str:
        """Save dock layout state"""
        state_bytes = bytes(self._state)  # type: ignore[call-overload]
        return state_bytes.hex() if state_bytes else ""


class DocumentTreeModel(QObject):
    """QML model for document/tree view - wraps Doorstop tree data"""

    # Signals
    itemsUpdated = Signal()
    itemSelected = Signal(str, str)  # itemId, docId
    documentSelected = Signal(str)
    refreshRequested = Signal()

    def __init__(self, doorstop_tree: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doorstop_tree = doorstop_tree
        self._items: list[dict[str, Any]] = []
        self._filterText = ""
        self._showInactive = False
        self._loadTree()

    @Slot(result="QVariantList")
    def items(self) -> list[dict[str, Any]]:
        """Current tree items as QML-accessible list"""
        return self._filterItems()

    def _filterItems(self) -> list[dict[str, Any]]:
        """Apply current filters to tree items"""
        items = self._items

        if self._filterText:
            text_lower = self._filterText.lower()
            items = [
                item
                for item in items
                if text_lower in item.get("title", "").lower() or text_lower in item.get("id", "").lower()
            ]

        if not self._showInactive:
            items = [item for item in items if item.get("status") != "closed"]

        return items

    @Slot(str)
    def setFilterText(self, filterText: str) -> None:
        """Update tree filter text"""
        if self._filterText != filterText:
            self._filterText = filterText
            self.itemsUpdated.emit()

    @Slot(bool)
    def setShowInactive(self, showInactive: bool) -> None:
        """Toggle showing inactive/closed items"""
        if self._showInactive != showInactive:
            self._showInactive = showInactive
            self.itemsUpdated.emit()

    @Slot(str, str)
    def selectItem(self, itemId: str, docId: str) -> None:
        """Select an item in the tree"""
        self.itemSelected.emit(itemId, docId)
        print(f"Item selected: {itemId} from {docId}")

    @Slot(str)
    def selectDocument(self, docId: str) -> None:
        """Select a document to view"""
        self.documentSelected.emit(docId)
        print(f"Document selected: {docId}")

    @Slot()
    def refreshTree(self) -> None:
        """Refresh tree data from Doorstop"""
        print("Refreshing tree...")
        self._loadTree()
        self.refreshRequested.emit()

    def _loadTree(self) -> None:
        """Load current Doorstop tree structure"""
        try:
            self._items = list(self._doorstop_tree.items())
            self.itemsUpdated.emit()
            print(f"Loaded {len(self._items)} items from tree")
        except Exception as e:
            print(f"Error loading tree: {e}")


class ItemEditorModel(QObject):
    """QML model for item editor - wraps Doorstop item data"""

    # Signals
    itemChanged = Signal()
    dirtyStateChanged = Signal(bool)
    validationError = Signal(str)
    saveRequested = Signal()
    undoRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._currentItem: dict[str, Any] | None = None
        self._isDirty = False
        self._hasUndoableChange = False

    @Property(object, notify=itemChanged)
    def currentItemData(self) -> dict[str, Any] | None:
        """Current item being edited"""
        return self._currentItem

    @Slot(str)
    def setCurrentItem(self, itemId: str) -> None:
        """Set current item to edit"""
        if itemId and itemId != (self._currentItem.get("id") if self._currentItem else None):
            # Load item from Doorstop
            print(f"Loading item: {itemId}")
            self._currentItem = {"id": itemId, "description": ""}
            self.itemChanged.emit()
            self.dirtyStateChanged.emit(False)

    @Property(bool, notify=dirtyStateChanged)
    def isDirty(self) -> bool:
        """Whether current edits have unsaved changes"""
        return self._isDirty

    @Slot(str)
    def setDescription(self, description: str) -> None:
        """Update item description - triggers dirty state"""
        if self._currentItem:
            self._currentItem["description"] = description
            self._isDirty = True
            self.itemChanged.emit()

    @Property(bool, notify=dirtyStateChanged)
    def hasUndoableChange(self) -> bool:
        """Whether undo is available"""
        return self._hasUndoableChange

    @Slot(result=str)
    def getUid(self) -> str:
        """Get current item UID (non-editable)"""
        if self._currentItem:
            return str(self._currentItem.get("id", ""))
        return "N/A"

    @Slot(str, result=bool)
    def validateFields(self, field_name: str) -> bool:
        """Validate a specific field"""
        # TODO: Implement validation logic
        return True

    @Slot()
    def saveItem(self) -> None:
        """Save current item changes to Doorstop"""
        if self._isDirty and self._currentItem:
            print(f"Saving item {self._currentItem['id']}")
            # Connect to actual Doorstop save: tree.items[id].save()
            self._isDirty = False
            self.dirtyStateChanged.emit(False)
            self.saveRequested.emit()

    @Slot()
    def undo(self) -> None:
        """Undo last change"""
        if self._hasUndoableChange:
            print("Undoing last change")
            # Implement undo logic
            self._hasUndoableChange = False
            self.undoRequested.emit()


class ItemRendererModel(QObject):
    """QML model for item renderer - handles document/item rendering"""

    # Signals
    documentLoaded = Signal(object)
    itemViewed = Signal(str)
    searchRequested = Signal(str)
    linkClicked = Signal(str, object)

    def __init__(self, render_worker: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._isRendering = False
        self._renderProgress = 0
        self._currentDocId = ""
        self._viewMode = "Document"  # Document, Section, Item
        self._render_worker = render_worker

    @Property(bool, notify=documentLoaded)
    def isRendering(self) -> bool:
        return self._isRendering

    @Property(int, notify=documentLoaded)
    def progressValue(self) -> int:
        return self._renderProgress

    @Slot(str, str)
    def renderDocument(self, docId: str, markdownContent: str) -> None:
        """Render a full document"""
        print(f"Rendering document: {docId}")
        self._isRendering = True
        self._currentDocId = docId

        # Process Markdown/PlantUML via render_worker.py
        self._render_worker.convert_markdown(markdownContent)

        # Load into QWebEngine
        # webEngine.loadHtml(html_content)

        self._isRendering = False
        self._renderProgress = 100
        self.documentLoaded.emit(docId)

    @Slot(str)
    def renderItem(self, itemId: str) -> None:
        """Render a single item"""
        print(f"Rendering item: {itemId}")
        self._viewMode = "Item"
        self.itemViewed.emit(itemId)

    @Slot(str)
    def setViewMode(self, mode: str) -> None:
        """Set render view mode"""
        if mode in ["Document", "Section", "Item"]:
            self._viewMode = mode
            print(f"View mode: {mode}")

    @Slot(str)
    def navigateToItem(self, itemId: str) -> None:
        """Navigate to a specific item"""
        self.itemViewed.emit(itemId)
        print(f"Navigated to item: {itemId}")

    @Slot(str)
    def performSearch(self, query: str) -> None:
        """Search within current document"""
        if query:
            self.searchRequested.emit(query)
            print(f"Searching for: {query}")


def setup_qml_bridge(
    engine: Any, doorstop_tree: Any, render_worker: Any, window_manager: WindowStateManager
) -> dict[str, Any]:
    """Register QML types and connect Python backend to QML

    Args:
        engine: QQmlApplicationEngine instance
        doorstop_tree: Doorstop tree object
        render_worker: Item renderer worker
        window_manager: WindowStateManager instance
    """

    # Register model classes as QML types
    qmlRegisterType(WindowStateManager, "DoorstopEdit", 1, 0, "WindowManager")  # type: ignore[call-overload]
    qmlRegisterType(DocumentTreeModel, "DoorstopEdit", 1, 0, "DocumentTreeModel")  # type: ignore[call-overload]
    qmlRegisterType(ItemEditorModel, "DoorstopEdit", 1, 0, "ItemEditorModel")  # type: ignore[call-overload]
    qmlRegisterType(ItemRendererModel, "DoorstopEdit", 1, 0, "ItemRendererModel")  # type: ignore[call-overload]

    # Create and expose model instances to QML context
    tree_model = DocumentTreeModel(doorstop_tree)
    engine.rootContext().setContextProperty("treeModel", tree_model)

    editor_model = ItemEditorModel()
    engine.rootContext().setContextProperty("itemEditorModel", editor_model)

    renderer_model = ItemRendererModel(render_worker)
    engine.rootContext().setContextProperty("rendererModel", renderer_model)

    window_manager.geometryChanged.connect(lambda: print("Geometry changed"))
    window_manager.stateChanged.connect(lambda: print("State changed"))

    print("QML bridge setup complete")
    return {
        "window_manager": window_manager,
        "tree_model": tree_model,
        "editor_model": editor_model,
        "renderer_model": renderer_model,
    }

"""
QML Components - Python wrapper classes for QML components
Bead: doorstop-edit-qml-frontend-migration-plan-lml.2.3

Purpose: Enable PySide6 to load custom QML types by registering them
"""

from typing import Any

from PySide6.QtCore import Property, QByteArray, QObject, Signal, Slot


class DocumentTreeModel(QObject):
    """Python model for QML TreeViewPanel - wraps Doorstop tree data"""

    # Signals for QML updates
    items_updated = Signal()
    filter_text_changed = Signal(str)

    def __init__(self, doorstop_tree: Any = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doorstop_tree = doorstop_tree
        self._items: list[dict[str, Any]] = []
        self._filter_text = ""
        self._show_inactive = False

    @Slot(result="QVariantList")
    def items(self) -> list[dict[str, Any]]:
        """Return current filtered tree items as QML-compatible list"""
        return self._filter_items()

    def _filter_items(self) -> list[dict[str, Any]]:
        """Apply filter and showInactive settings to returned items"""
        if not self._doorstop_tree:
            return []

        items = list(self._doorstop_tree.items())

        # Apply text filter (case-insensitive)
        if self._filter_text:
            text_lower = self._filter_text.lower()
            items = [
                item
                for item in items
                if text_lower in str(item.get("title", "")).lower() or text_lower in str(item.get("id", "")).lower()
            ]

        # Apply showInactive setting (show closed items)
        if not self._show_inactive:
            items = [item for item in items if str(item.get("status", "")).lower() != "closed"]

        return items

    @Slot(str)
    def setFilterText(self, text: str) -> None:
        """Set filter text - triggers signal to update QML"""
        self._filter_text = text
        print(f"Tree filter set to: '{text}'")
        self.items_updated.emit()

    @Slot(bool)
    def setShowInactive(self, show_inactive: bool) -> None:
        """Toggle showing inactive/closed items"""
        self._show_inactive = show_inactive
        print(f"Show inactive items: {show_inactive}")
        self.items_updated.emit()

    @Property(str)
    def filterText(self) -> str:
        return self._filter_text

    @Slot()
    def refreshTree(self) -> None:
        """Refresh tree data from Doorstop backend"""
        if self._doorstop_tree:
            print("Refreshing tree data...")
            self.items_updated.emit()


class ItemEditorModel(QObject):
    """Python model for QML ItemEditorPanel - handles item editing with dirty state tracking"""

    # Signals for QML updates
    current_item_changed = Signal()
    dirty_state_changed = Signal(bool)
    validation_error = Signal(str, str)  # (field_name, error_message)

    def __init__(self, doorstop_tree: Any = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doorstop_tree = doorstop_tree
        self._current_item: dict[str, Any] | None = None
        self._is_dirty = False
        self._original_data: dict[str, Any] = {}

    @Slot(result="QVariantMap")
    def getCurrentItemData(self) -> dict[str, str]:
        """Return current item data as QML-compatible map"""
        if not self._current_item:
            return {}

        # Convert item to dict for QML
        return {
            "id": str(self._current_item.get("id", "")),
            "uid": str(self._current_item.get("uid", "")),
            "title": str(self._current_item.get("title", "")),
            "description": str(self._current_item.get("description", "")),
            "status": str(self._current_item.get("status", "")),
            "priority": str(self._current_item.get("priority", "")),
            "parent": str(self._current_item.get("parent", "")),
        }

    @Slot(str, result=str)
    def getUid(self) -> str:
        """Return current item UID"""
        if self._current_item:
            return str(self._current_item.get("uid", ""))
        return ""

    @Slot(str, str)
    def setFieldValue(self, field_name: str, value: Any) -> None:
        """Update a field value - marks item as dirty if changed"""
        if not self._current_item:
            return

        original_value = self._current_item.get(field_name, "")
        if str(original_value) != str(value):
            self._current_item[field_name] = value
            if not self._is_dirty:
                self._is_dirty = True
                self.dirty_state_changed.emit(True)
                print(f"Item marked dirty - field '{field_name}' changed")

    @Slot()
    def saveItem(self) -> None:
        """Save current item changes"""
        if not self._current_item or not self._is_dirty:
            return

        # Here we would actually save to Doorstop backend
        print(f"Saving item: {self._current_item.get('id', 'unknown')}")

        # Clear dirty state
        self._is_dirty = False
        self.dirty_state_changed.emit(False)

        # Update original data snapshot
        self._original_data = self._current_item.copy()

    @Slot()
    def undoChanges(self) -> None:
        """Revert changes to original state"""
        if not self._current_item or not self._is_dirty:
            return

        # Restore original values
        if self._original_data:
            self._current_item.update(self._original_data)

        self._is_dirty = False
        self.dirty_state_changed.emit(False)
        self.current_item_changed.emit()
        print("Changes undone - item restored to original state")

    @Slot(str)
    def validateField(self, field_name: str) -> bool:
        """Validate a field and emit error if invalid"""
        if not self._current_item:
            return True

        value = str(self._current_item.get(field_name, ""))

        # Basic validation rules
        if field_name == "id":
            if not value or len(value) < 3:
                self.validation_error.emit(field_name, "ID must be at least 3 characters")
                return False
        elif field_name == "title":
            if not value.strip():
                self.validation_error.emit(field_name, "Title cannot be empty")
                return False

        return True

    @Slot()
    def clearEditor(self) -> None:
        """Clear the editor state"""
        self._current_item = None
        self._is_dirty = False
        self.current_item_changed.emit()
        print("Editor cleared")

    # Properties for QML binding
    @Property(bool, notify=dirty_state_changed)
    def isDirty(self) -> bool:
        return self._is_dirty

    def loadItem(self, item_data: dict[str, Any]) -> None:
        """Load item into editor"""
        if isinstance(item_data, dict):
            self._current_item = item_data.copy()
            self._original_data = item_data.copy()
            self._is_dirty = False
            self.current_item_changed.emit()
            print(f"Loaded item: {item_data.get('id', 'unknown')}")


class ItemRendererModel(QObject):
    """Python model for QML ItemRenderer - handles document rendering with progress tracking"""

    # Signals for QML updates
    render_progress_changed = Signal(int)  # 0-100 progress
    render_started = Signal()
    render_completed = Signal()
    view_mode_changed = Signal(str)  # document/section/item
    search_requested = Signal(str)  # search query

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_document: str | None = None
        self._current_item: str | None = None
        self._is_rendering = False
        self._progress_value = 0
        self._view_mode = "document"
        self._search_query = ""

    @Slot(str)
    def renderDocument(self, document_id: str) -> None:
        """Start rendering a document"""
        if not document_id:
            return

        print(f"Starting document render: {document_id}")
        self._current_document = document_id
        self._is_rendering = True
        self._progress_value = 0
        self.render_started.emit()
        self.render_progress_changed.emit(0)

        # Simulate progressive rendering (in real implementation this would be async)
        self._simulate_render_progress()

    @Slot(str, str)
    def renderItem(self, item_id: str, content: str) -> None:
        """Render a specific item with content"""
        print(f"Rendering item: {item_id}")
        self._current_item = item_id
        self._view_mode = "item"
        self.view_mode_changed.emit("item")
        self.render_started.emit()
        self.render_progress_changed.emit(50)

        # Simulate completion
        self._progress_value = 100
        self.render_progress_changed.emit(100)
        self._is_rendering = False
        self.render_completed.emit()

    def _simulate_render_progress(self) -> None:
        """Simulate progressive rendering for testing"""

        # In real implementation, this would be connected to actual rendering events
        progress_steps = [25, 50, 75, 100]

        for step in progress_steps:
            # Small delay to simulate work (in real app this would be event-driven)
            # time.sleep(0.1)  # Commented out for testing
            self._progress_value = step
            self.render_progress_changed.emit(step)

            if step == 100:
                self._is_rendering = False
                self.render_completed.emit()

    @Slot(str)
    def setSearchQuery(self, query: str) -> None:
        """Set search query for document search"""
        self._search_query = query
        print(f"Search query set: '{query}'")
        self.search_requested.emit(query)

    @Slot(str)
    def setViewMode(self, mode: str) -> None:
        """Set view mode (document/section/item)"""
        if mode in ["document", "section", "item"]:
            self._view_mode = mode
            print(f"View mode changed to: {mode}")
            self.view_mode_changed.emit(mode)

    @Slot()
    def clearRenderer(self) -> None:
        """Clear the current rendering state"""
        self._current_document = None
        self._current_item = None
        self._is_rendering = False
        self._progress_value = 0
        self._view_mode = "document"
        print("Renderer cleared")

    # Properties for QML binding
    @Property(int, notify=render_progress_changed)
    def progressValue(self) -> int:
        return self._progress_value

    @Property(bool)
    def isRendering(self) -> bool:
        return self._is_rendering

    @Property(str, notify=view_mode_changed)
    def viewMode(self) -> str:
        return self._view_mode

    def getCurrentContent(self) -> dict[str, Any]:
        """Get current rendered content (for testing)"""
        return {
            "document": self._current_document,
            "item": self._current_item,
            "view_mode": self._view_mode,
            "progress": self._progress_value,
        }


class WindowStateManager(QObject):
    """Python manager for QML window state persistence"""

    # Signals
    geometry_saved = Signal()
    geometry_restored = Signal()
    state_saved = Signal()
    state_restored = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._saved_geometry = QByteArray()
        self._saved_state = QByteArray()
        self._window_width = 1200
        self._window_height = 800

    @Slot(int, int, int, int)
    def saveGeometry(self, x: int, y: int, width: int, height: int) -> None:
        """Save window geometry as QByteArray (hex encoded)"""
        # In real implementation, this would use QMainWindow.saveGeometry()
        # For QML, we store individual values
        self._window_width = width
        self._window_height = height

        # Create a QByteArray with geometry data (simplified)
        import struct

        geometry_data = struct.pack("iiii", x, y, width, height)
        self._saved_geometry = QByteArray(geometry_data)

        self.geometry_saved.emit()
        print(f"Geometry saved: {width}x{height} at ({x},{y})")

    @Slot(result="QByteArray")
    def getSavedGeometry(self) -> QByteArray:
        """Return saved geometry as QByteArray"""
        return self._saved_geometry

    @Slot("QByteArray")
    def restoreGeometry(self, geometry_data: QByteArray) -> None:
        """Restore geometry from QByteArray"""
        if not geometry_data.isEmpty():
            self._saved_geometry = QByteArray(geometry_data)
            import struct

            x, y, width, height = struct.unpack("iiii", geometry_data.data())
            self._window_width = width
            self._window_height = height
            self.geometry_restored.emit()
            print(f"Geometry restored: {width}x{height} at ({x},{y})")

    @Slot(str)
    def saveState(self, state_data: str) -> None:
        """Save window state (dock positions, etc.)"""
        self._saved_state = QByteArray(state_data.encode())
        self.state_saved.emit()
        print(f"Window state saved: {len(state_data)} bytes")

    @Slot(result=str)
    def getSavedState(self) -> str:
        """Return saved state as string"""
        state_bytes = bytes(self._saved_state)  # type: ignore[call-overload]
        return state_bytes.decode() if state_bytes else ""

    # Properties for QML binding
    @Property(int)
    def windowWidth(self) -> int:
        return self._window_width

    @Property(int)
    def windowHeight(self) -> int:
        return self._window_height

    @Property(QByteArray)
    def savedGeometry(self) -> QByteArray:
        return self._saved_geometry


class PinnedItemsModel(QObject):
    """Python model for QML PinnedItemsPanel - manages pinned items list"""

    # Signals
    pinned_items_changed = Signal()
    item_pinned = Signal(str)  # item_id
    item_unpinned = Signal(str)  # item_id
    items_cleared = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pinned_items: list[dict[str, Any]] = []  # List of item dictionaries

    @Slot(result="QVariantList")
    def pinnedItems(self) -> list[dict[str, Any]]:
        """Return current pinned items as QML-compatible list"""
        return self._pinned_items.copy()

    @Slot("QVariantMap")
    def addPinnedItem(self, item_data: Any) -> None:
        """Add an item to pinned list"""
        if not isinstance(item_data, dict):
            return

        item_id = str(item_data.get("id", ""))
        if not item_id:
            return

        # Check if already pinned
        for item in self._pinned_items:
            if str(item.get("id", "")) == item_id:
                print(f"Item {item_id} is already pinned")
                return

        # Add to pinned list
        self._pinned_items.append(item_data.copy())
        self.pinned_items_changed.emit()
        self.item_pinned.emit(item_id)
        print(f"Item pinned: {item_id}")

    @Slot(str)
    def removePinnedItem(self, item_id: str) -> None:
        """Remove an item from pinned list"""
        initial_count = len(self._pinned_items)
        self._pinned_items = [item for item in self._pinned_items if str(item.get("id", "")) != item_id]

        if len(self._pinned_items) < initial_count:
            self.pinned_items_changed.emit()
            self.item_unpinned.emit(item_id)
            print(f"Item unpinned: {item_id}")

    @Slot()
    def clearAllPinnedItems(self) -> None:
        """Clear all pinned items"""
        if self._pinned_items:
            self._pinned_items.clear()
            self.pinned_items_changed.emit()
            self.items_cleared.emit()
            print("All pinned items cleared")

    @Slot(str, result=bool)
    def isItemPinned(self, item_id: str) -> bool:
        """Check if an item is pinned"""
        for item in self._pinned_items:
            if str(item.get("id", "")) == item_id:
                return True
        return False

    @Slot(result=int)
    def pinnedItemsCount(self) -> int:
        """Return count of pinned items"""
        return len(self._pinned_items)


class TreeViewPanel(QObject):
    """Python wrapper for QML TreeViewPanel component"""

    item_selected = Signal(str, str)  # itemId, docId
    document_selected = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._filter_text = ""
        self._show_inactive = False

    @Slot(str)
    def setFilterText(self, text: str) -> None:
        """Set filter text for tree view"""
        self._filter_text = text

    @Slot(bool)
    def setShowInactive(self, show: bool) -> None:
        """Toggle showing inactive items"""
        self._show_inactive = show

    @Property(str)
    def filterText(self) -> str:
        return self._filter_text


class ItemEditorPanel(QObject):
    """Python wrapper for QML ItemEditorPanel component"""

    item_edited = Signal(str, object)  # itemId, newData
    save_requested = Signal()
    validation_error = Signal(str)
    undo_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._is_dirty = False

    @Slot(str)
    def setCurrentItem(self, item_id: str) -> None:
        """Set current item being edited"""
        print(f"Editing item: {item_id}")

    @Slot()
    def saveChanges(self) -> None:
        """Save current item changes"""
        self.save_requested.emit()

    @Slot(str)
    def setDescription(self, description: str) -> None:
        """Update item description"""
        print(f"Description updated: {description[:50]}...")


class ItemRenderer(QObject):
    """Python wrapper for QML ItemRenderer component"""

    document_loaded = Signal(str)
    item_viewed = Signal(str)
    search_requested = Signal(str)
    link_clicked = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._is_rendering = False

    @Slot(str, str)
    def renderDocument(self, doc_id: str, content: str) -> None:
        """Render a document"""
        print(f"Rendering document {doc_id}")
        self.document_loaded.emit(doc_id)

    @Slot(str)
    def renderItem(self, item_id: str) -> None:
        """Render a single item"""
        print(f"Rendering item {item_id}")
        self.item_viewed.emit(item_id)


class PinnedItemsPanel(QObject):
    """Python wrapper for QML PinnedItemsPanel component"""

    item_pinned = Signal(str, object)  # itemId, itemData
    item_unpinned = Signal(str)
    items_cleared = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pinned_items: list[dict[str, Any]] = []

    @Slot(str, object)
    def addPinnedItem(self, item_id: str, item_data: dict[str, Any]) -> None:
        """Add an item to pinned list"""
        if item_id not in [item["id"] for item in self._pinned_items]:
            self._pinned_items.append({"id": item_id, **item_data})
            print(f"Pinned item {item_id}")
            self.item_pinned.emit(item_id, item_data)

    @Slot(int)
    def removePinnedItem(self, index: int) -> None:
        """Remove pinned item at index"""
        if 0 <= index < len(self._pinned_items):
            removed = self._pinned_items.pop(index)
            print(f"Unpinned item {removed['id']}")
            self.item_unpinned.emit(removed["id"])

    @Slot()
    def clearAll(self) -> None:
        """Clear all pinned items"""
        while self._pinned_items:
            removed = self._pinned_items.pop(0)
            self.item_unpinned.emit(removed["id"])
        print("Cleared all pinned items")


def setup_qml_components(engine: Any) -> dict[str, Any]:
    """Register all QML components with the engine"""

    # Create component instances
    tree_view = TreeViewPanel()
    item_editor = ItemEditorPanel()
    item_renderer = ItemRenderer()
    pinned_items = PinnedItemsPanel()

    # Register as context properties (easier for testing)
    engine.rootContext().setContextProperty("TreeViewPanel", tree_view)
    engine.rootContext().setContextProperty("ItemEditorPanel", item_editor)
    engine.rootContext().setContextProperty("ItemRenderer", item_renderer)
    engine.rootContext().setContextProperty("PinnedItemsPanel", pinned_items)

    print("Registered QML components successfully")
    return {
        "tree_view": tree_view,
        "item_editor": item_editor,
        "item_renderer": item_renderer,
        "pinned_items": pinned_items,
    }

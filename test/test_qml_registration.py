"""
Test Suite: QML Component Registration
Bead: doorstop-edit-qml-frontend-migration-plan-lml.2.3

Purpose: Helper function to register QML components for testing
This is needed because PySide6 requires explicit registration of custom QML types.
"""

from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtQml import qmlRegisterType


def register_qml_components(engine: Any) -> dict[str, type[QObject]]:
    """
    Register all custom QML components with the QML engine.

    Args:
        engine: QQmlApplicationEngine instance

    Returns:
        dict: Mapped component classes for testing access
    """

    # Import QML components (they will be lazy-loaded via imports)
    from doorstop_edit.ui.qml_components import (
        ItemEditorPanel,
        ItemRenderer,
        PinnedItemsPanel,
        TreeViewPanel,
    )

    qmlRegisterType(TreeViewPanel, "DoorstopEdit", 1, 0, "TreeViewPanel")  # type: ignore[call-overload]
    qmlRegisterType(ItemEditorPanel, "DoorstopEdit", 1, 0, "ItemEditorPanel")  # type: ignore[call-overload]
    qmlRegisterType(ItemRenderer, "DoorstopEdit", 1, 0, "ItemRenderer")  # type: ignore[call-overload]
    qmlRegisterType(PinnedItemsPanel, "DoorstopEdit", 1, 0, "PinnedItemsPanel")  # type: ignore[call-overload]

    return {
        "tree_view": TreeViewPanel,
        "item_editor": ItemEditorPanel,
        "item_renderer": ItemRenderer,
        "pinned_items": PinnedItemsPanel,
    }


class DummyWindowManager(QObject):
    """Dummy window manager for tests"""

    pass

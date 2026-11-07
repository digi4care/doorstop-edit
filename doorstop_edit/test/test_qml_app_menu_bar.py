"""Standalone AppMenuBar contract; no Main.qml or backend integration assumed."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMetaObject, QObject, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication


@pytest.fixture
def menu(qapp: QApplication) -> Iterator[QObject]:
    engine = QQmlEngine()
    path = Path(__file__).resolve().parents[1] / "qml" / "AppMenuBar.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    assert component.isReady(), [error.toString() for error in component.errors()]
    root = component.create()
    assert root is not None, [error.toString() for error in component.errors()]
    yield root
    root.deleteLater()
    component.deleteLater()
    engine.deleteLater()
    qapp.processEvents()


def action(menu: QObject, name: str) -> QObject:
    result = menu.findChild(QObject, name + "Action")
    assert result is not None, name
    return result


def trigger(menu: QObject, name: str) -> None:
    assert QMetaObject.invokeMethod(action(menu, name), "trigger")


def test_menu_actions_emit_host_intents(menu: QObject) -> None:
    titles = [child.property("title") for child in menu.children() if child.property("title")]
    assert titles == ["File", "View", "Help"]
    menu.setProperty("hasProject", True)
    menu.setProperty("hasSelection", True)

    requests = (
        ("openFolder", "openFolderRequested"),
        ("saveItem", "saveItemRequested"),
        ("focusProjectLocation", "focusProjectLocationRequested"),
        ("validateProject", "validateProjectRequested"),
        ("settings", "settingsRequested"),
        ("exit", "exitRequested"),
        ("graph", "graphRequested"),
        ("validationResults", "validationResultsRequested"),
        ("about", "aboutRequested"),
    )
    for name, signal_name in requests:
        received: list[tuple[object, ...]] = []
        getattr(menu, signal_name).connect(lambda *args: received.append(args))
        trigger(menu, name)
        assert received == [()], name

    for name, signal_name, property_name in (
        ("documentTree", "documentTreeVisibilityRequested", "documentTreeVisible"),
        ("itemEditor", "itemEditorVisibilityRequested", "itemEditorVisible"),
        ("pinnedItems", "pinnedItemsVisibilityRequested", "pinnedItemsVisible"),
    ):
        received_visibility: list[bool] = []
        getattr(menu, signal_name).connect(received_visibility.append)
        assert action(menu, name).property("checked") is True
        trigger(menu, name)
        assert received_visibility == [False]
        menu.setProperty(property_name, False)
        menu.setProperty(property_name, True)
        assert action(menu, name).property("checked") is True


def test_shortcuts_enabled_state_and_accessible_names(menu: QObject) -> None:
    shortcut_actions = ("openFolder", "saveItem", "focusProjectLocation", "graph")
    assert {name: action(menu, name).property("shortcut") for name in shortcut_actions} == {
        "openFolder": "Ctrl+O",
        "saveItem": "Ctrl+S",
        "focusProjectLocation": "Ctrl+L",
        "graph": "Ctrl+G",
    }
    assert not action(menu, "saveItem").property("enabled")
    assert not action(menu, "validateProject").property("enabled")
    assert not action(menu, "validationResults").property("enabled")
    menu.setProperty("hasProject", True)
    menu.setProperty("hasSelection", True)
    for name in ("saveItem", "validateProject", "validationResults"):
        assert action(menu, name).property("enabled")

    names = {
        "openFolder": "Open project folder",
        "saveItem": "Save current item",
        "focusProjectLocation": "Focus project location",
        "validateProject": "Validate all documents and items",
        "settings": "Open settings",
        "exit": "Exit Doorstop Edit",
        "documentTree": "Show document tree",
        "itemEditor": "Show item editor",
        "pinnedItems": "Show pinned items",
        "graph": "Open project graph",
        "validationResults": "Open project validation results",
        "about": "About Doorstop Edit",
    }
    for name, expected in names.items():
        parent = action(menu, name).parent()
        assert parent is not None
        interface = QAccessible.queryAccessibleInterface(parent)
        assert interface is not None
        assert interface.text(QAccessible.Text.Name) == expected

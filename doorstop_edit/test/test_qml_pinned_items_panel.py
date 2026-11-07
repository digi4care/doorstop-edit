"""Standalone Qt Quick checks for the pinned-items intent surface."""

from pathlib import Path
from typing import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


@pytest.fixture
def pinned_panel(qapp: QApplication, qtbot: QtBot) -> Iterator[tuple[QQuickItem, QQuickItem, QQuickWindow]]:
    engine = QQmlEngine()
    qml_path = Path(__file__).parents[1] / "qml" / "PinnedItemsPanel.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_path)))
    assert component.isReady(), component.errors()
    panel = component.create()
    assert isinstance(panel, QQuickItem), component.errors()
    window = QQuickWindow()
    window.setWidth(380)
    window.setHeight(330)
    panel.setParentItem(window.contentItem())
    panel.setWidth(380)
    panel.setHeight(330)
    window.show()
    rows = panel.findChild(QQuickItem, "pinnedItemsList")
    assert rows is not None
    qtbot.waitUntil(window.isActive)
    yield panel, rows, window
    panel.setParentItem(None)
    panel.deleteLater()
    window.close()
    window.deleteLater()
    component.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_keyboard_selection_and_open_intent(
    pinned_panel: tuple[QQuickItem, QQuickItem, QQuickWindow], qtbot: QtBot
) -> None:
    panel, rows, window = pinned_panel
    opened: list[str] = []
    panel.openRequested.connect(opened.append)
    panel.setProperty(
        "pinnedItems",
        [
            {"uid": "REQ-001", "level": "1", "header": "First"},
            {"uid": "REQ-002", "level": "2", "header": "Second"},
        ],
    )
    qtbot.waitUntil(lambda: rows.property("count") == 2)
    rows.forceActiveFocus()
    qtbot.waitUntil(lambda: rows.property("activeFocus"))
    QTest.keyClick(window, Qt.Key.Key_Down)
    assert panel.property("selectedUid") == "REQ-002"
    QTest.keyClick(window, Qt.Key.Key_Return)
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert opened == ["REQ-002", "REQ-002"]


def test_unpin_is_host_intent_not_local_removal(
    pinned_panel: tuple[QQuickItem, QQuickItem, QQuickWindow], qtbot: QtBot
) -> None:
    panel, rows, window = pinned_panel
    removed: list[str] = []
    panel.unpinRequested.connect(removed.append)
    panel.setProperty("pinnedItems", [{"uid": "REQ-001", "header": "First"}])
    qtbot.waitUntil(lambda: rows.property("count") == 1)
    rows.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Delete)
    assert removed == ["REQ-001"]
    assert rows.property("count") == 1  # Host owns the data and must refresh it.
    button = panel.findChild(QObject, "pinnedUnpinButton")
    assert button is not None
    button.clicked.emit()
    assert removed == ["REQ-001", "REQ-001"]


def test_empty_and_malformed_rows_do_not_activate(
    pinned_panel: tuple[QQuickItem, QQuickItem, QQuickWindow], qtbot: QtBot
) -> None:
    panel, rows, window = pinned_panel
    opened: list[str] = []
    removed: list[str] = []
    panel.openRequested.connect(opened.append)
    panel.unpinRequested.connect(removed.append)
    panel.setProperty("pinnedItems", [None, {}, {"uid": ""}])
    qtbot.waitUntil(lambda: rows.property("count") == 0)
    rows.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Return)
    QTest.keyClick(window, Qt.Key.Key_Delete)
    assert panel.property("selectedUid") == ""
    assert not opened and not removed
    assert not panel.findChild(QObject, "pinnedOpenButton").property("enabled")
    panel.setProperty("pinnedItems", None)
    assert rows.property("count") == 0


def test_refresh_preserves_uid_then_drops_removed_selection(
    pinned_panel: tuple[QQuickItem, QQuickItem, QQuickWindow], qtbot: QtBot
) -> None:
    panel, rows, window = pinned_panel
    opened: list[str] = []
    removed: list[str] = []
    panel.openRequested.connect(opened.append)
    panel.unpinRequested.connect(removed.append)
    panel.setProperty("pinnedItems", [{"uid": "A"}, {"uid": "B"}, {"uid": "C"}])
    qtbot.waitUntil(lambda: rows.property("count") == 3)
    rows.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Down)
    assert panel.property("selectedUid") == "B"
    panel.setProperty("pinnedItems", [{"uid": "C"}, {"uid": "B"}, {"uid": "A"}])
    assert panel.property("selectedUid") == "B"
    assert rows.property("currentIndex") == 1
    panel.setProperty("pinnedItems", [{"uid": "C"}, {"uid": "A"}])
    assert panel.property("selectedUid") == "A"  # Nearest surviving index, never B.
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert opened == ["A"]
    panel.setProperty("pinnedItems", [{"uid": "C", "available": False}])
    assert panel.property("selectedUid") == "C"
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert opened == ["A"]  # Deleted item cannot be opened.
    QTest.keyClick(window, Qt.Key.Key_Delete)
    assert removed == ["C"]  # But its stale pin can be removed.
    panel.setProperty("pinnedItems", [])
    assert panel.property("selectedUid") == ""
    assert rows.property("currentIndex") == -1
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert opened == ["A"]

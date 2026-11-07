"""Standalone Qt Quick contract for item editor utility intents."""

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


@pytest.fixture
def utilities_host(qapp: QApplication, qtbot: QtBot) -> Any:
    engine = QQmlApplicationEngine()
    component = QQmlComponent(engine)
    source = b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    width: 660; height: 180; visible: true
    App.EditorUtilities { width: parent.width; height: 54 }
}"""
    component.setData(source, QUrl.fromLocalFile(str(Path(__file__).resolve())))
    assert component.isReady(), component.errors()
    window = component.create()
    assert isinstance(window, QQuickWindow), component.errors()
    toolbar = window.findChild(QQuickItem, "editorUtilities")
    assert toolbar is not None
    qtbot.waitExposed(window)
    # QML WindowShortcut only fires in the active window. The previous test may
    # have closed its window without the next one becoming the focus window.
    window.requestActivate()
    qtbot.waitUntil(lambda: QApplication.focusWindow() is window and window.isActive())
    yield window, toolbar
    window.close()
    window.deleteLater()
    engine.deleteLater()
    qapp.processEvents()


def button(toolbar: QQuickItem, name: str) -> QQuickItem:
    result = toolbar.findChild(QQuickItem, name)
    assert result is not None
    return result


def click(window: QQuickWindow, target: QQuickItem) -> None:
    point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2))
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(point.x()), round(point.y()))
    )


def test_disabled_actions_and_explicit_host_intents(utilities_host: Any) -> None:
    window, toolbar = utilities_host
    events: list[tuple[str, Any]] = []
    toolbar.undoRequested.connect(lambda: events.append(("undo", None)))
    toolbar.formatRequested.connect(lambda: events.append(("format", None)))
    toolbar.wrapTextRequested.connect(lambda value: events.append(("wrap", value)))
    toolbar.copyUidRequested.connect(lambda uid: events.append(("copy", uid)))
    undo = button(toolbar, "undoItemButton")
    format_text = button(toolbar, "formatTextButton")
    wrap = button(toolbar, "wrapTextButton")
    copy = button(toolbar, "copyUidButton")

    assert not undo.isEnabled() and not format_text.isEnabled() and not copy.isEnabled()
    assert wrap.isEnabled()
    click(window, undo)
    click(window, format_text)
    click(window, copy)
    assert events == []
    click(window, wrap)
    assert events == [("wrap", True)]
    assert not toolbar.property("wrapText")  # host has not accepted the requested change
    toolbar.setProperty("wrapText", True)
    assert wrap.property("text") == "Wrap: On"
    click(window, wrap)
    assert events[-1] == ("wrap", False)

    toolbar.setProperty("undoAvailable", True)
    toolbar.setProperty("formatAvailable", True)
    assert not undo.isEnabled() and not format_text.isEnabled()
    toolbar.setProperty("itemUid", "REQ-001")
    assert undo.isEnabled() and format_text.isEnabled() and copy.isEnabled()
    click(window, undo)
    click(window, format_text)
    click(window, copy)
    assert events[-3:] == [("undo", None), ("format", None), ("copy", "REQ-001")]

    toolbar.setProperty("itemUid", "")
    assert not undo.isEnabled() and not format_text.isEnabled() and not copy.isEnabled()
    assert wrap.isEnabled()  # preference remains available with no selection


def test_accessible_names_keyboard_and_format_shortcut(utilities_host: Any, qtbot: QtBot) -> None:
    window, toolbar = utilities_host
    toolbar.setProperty("itemUid", "REQ-002")
    toolbar.setProperty("undoAvailable", True)
    toolbar.setProperty("formatAvailable", True)
    names = {
        "undoItemButton": "Undo all changes to selected item",
        "formatTextButton": "Format focused text field",
        "wrapTextButton": "Text wrap off",
        "copyUidButton": "Copy selected item UID",
    }
    for name, expected in names.items():
        control = button(toolbar, name)
        interface = QAccessible.queryAccessibleInterface(control)
        assert interface is not None
        assert interface.text(QAccessible.Text.Name) == expected
        assert control.activeFocusOnTab()

    events: list[str] = []
    toolbar.undoRequested.connect(lambda: events.append("undo"))
    toolbar.wrapTextRequested.connect(lambda wrapped: events.append(f"wrap:{wrapped}"))
    toolbar.formatRequested.connect(lambda: events.append("format"))
    toolbar.copyUidRequested.connect(lambda _: events.append("copy"))
    for name, expected in (("undoItemButton", "undo"), ("wrapTextButton", "wrap:True"), ("copyUidButton", "copy")):
        control = button(toolbar, name)
        control.forceActiveFocus()
        qtbot.keyClick(window, Qt.Key.Key_Space)
        assert events[-1] == expected
    toolbar.setProperty("wrapText", True)
    wrap_interface = QAccessible.queryAccessibleInterface(button(toolbar, "wrapTextButton"))
    assert wrap_interface is not None
    assert wrap_interface.text(QAccessible.Text.Name) == "Text wrap on"
    qtbot.keyClick(window, Qt.Key.Key_Q, modifier=Qt.KeyboardModifier.AltModifier)
    assert events[-1] == "format"

    toolbar.setProperty("formatAvailable", False)
    qtbot.keyClick(window, Qt.Key.Key_Q, modifier=Qt.KeyboardModifier.AltModifier)
    assert events.count("format") == 1

"""Standalone QML item-editor contract (no backend or Main.qml)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


@pytest.fixture
def form(qapp: QApplication) -> Iterator[tuple[QQuickWindow, QQuickItem]]:
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(
        b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    visible: true; width: 500; height: 600
    property var schema: []
    property var snapshot: ({})
    property var validation: ({})
    App.ItemEditorFields {
        objectName: "editor"
        anchors.fill: parent
        fields: schema
        values: snapshot
        errors: validation
    }
}""",
        QUrl.fromLocalFile(str(Path(__file__).resolve())),
    )
    assert component.isReady(), component.errors()
    window = component.create()
    assert isinstance(window, QQuickWindow), component.errors()
    editor = window.findChild(QObject, "editor")
    assert isinstance(editor, QQuickItem)
    qapp.processEvents()
    yield window, editor
    window.close()
    window.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def visual_item(root: QQuickItem, name: str) -> QQuickItem:
    """Repeater delegates are visual children, not QObject children of the form."""
    if root.objectName() == name:
        return root
    for child in root.childItems():
        try:
            return visual_item(child, name)
        except LookupError:
            pass
    raise LookupError(name)


def test_all_fields_visible_in_order_with_unsupported_and_missing_values(
    form: tuple[QQuickWindow, QQuickItem], qapp: QApplication
) -> None:
    window, editor = form
    window.setProperty(
        "schema",
        [
            {"key": "header", "label": "Header", "kind": "text"},
            {"key": "body", "label": "Text", "kind": "multiline"},
            {"key": "active", "label": "Active", "kind": "boolean"},
            {"key": "links", "label": "Links", "kind": "links"},
            {"key": "missing", "label": "Missing", "kind": "text"},
            {"key": "odd", "label": "Odd", "kind": "boolean"},
        ],
    )
    window.setProperty(
        "snapshot", {"header": "Heading", "body": "Line\nTwo", "active": False, "links": ["REQ-1"], "odd": "false"}
    )
    qapp.processEvents()
    for index, label in enumerate(("Header", "Text", "Active", "Links", "Missing", "Odd")):
        assert visual_item(editor, f"fieldLabel_{index}").property("text") == label
    assert visual_item(editor, "fieldInput_0").property("text") == "Heading"
    assert visual_item(editor, "fieldInput_1").property("text") == "Line\nTwo"
    assert visual_item(editor, "fieldInput_2").property("checked") is False
    assert "REQ-1" in visual_item(editor, "fieldFallback_3").property("text")
    assert "Value not supplied" in visual_item(editor, "fieldFallback_4").property("text")
    assert "false" in visual_item(editor, "fieldFallback_5").property("text")
    assert "not editable" in visual_item(editor, "fieldFallback_5").property("text")


def test_keyboard_edits_and_host_owned_save_revert_intents(form: tuple[QQuickWindow, QQuickItem], qtbot: QtBot) -> None:
    window, editor = form
    window.setProperty(
        "schema",
        [
            {"key": "header", "label": "Header", "kind": "text"},
            {"key": "body", "label": "Body", "kind": "multiline"},
            {"key": "active", "label": "Active", "kind": "boolean"},
        ],
    )
    window.setProperty("snapshot", {"header": "A", "body": "B", "active": False})
    edits: list[tuple[str, object]] = []
    saves: list[bool] = []
    reverts: list[bool] = []
    editor.fieldEdited.connect(lambda key, value: edits.append((key, value)))
    editor.saveRequested.connect(lambda: saves.append(True))
    editor.revertRequested.connect(lambda: reverts.append(True))
    header = visual_item(editor, "fieldInput_0")
    body = visual_item(editor, "fieldInput_1")
    active = visual_item(editor, "fieldInput_2")
    header.forceActiveFocus()
    qtbot.keyClick(window, Qt.Key.Key_X)
    assert edits[-1] == ("header", "Ax")
    assert window.property("snapshot")["header"] == "A"  # no mutation
    qtbot.keyClick(window, Qt.Key.Key_Tab)
    assert body.property("activeFocus")
    qtbot.keyClick(window, Qt.Key.Key_Backtab)
    assert header.property("activeFocus")
    body.forceActiveFocus()
    body.setProperty("cursorPosition", len(body.property("text")))
    qtbot.keyClick(window, Qt.Key.Key_Z)
    assert edits[-1] == ("body", "Bz")
    active.forceActiveFocus()
    qtbot.keyClick(window, Qt.Key.Key_Space)
    assert edits[-1] == ("active", True)
    assert window.property("snapshot")["active"] is False

    editor.setProperty("dirty", True)
    editor.setProperty("canSave", True)
    editor.setProperty("canRevert", True)
    save = visual_item(editor, "saveButton")
    revert = visual_item(editor, "revertButton")
    save.forceActiveFocus()
    qtbot.keyClick(window, Qt.Key.Key_Space)
    revert.forceActiveFocus()
    qtbot.keyClick(window, Qt.Key.Key_Space)
    assert saves == [True]
    assert reverts == [True]
    editor.setProperty("pending", True)
    assert not save.property("enabled")
    assert not revert.property("enabled")
    assert not active.property("enabled")
    editor.setProperty("pending", False)
    editor.setProperty("readOnly", True)
    assert header.property("readOnly")
    assert not save.property("enabled")
    assert not revert.property("enabled")


def test_host_snapshot_errors_and_field_access(
    form: tuple[QQuickWindow, QQuickItem], qapp: QApplication, qtbot: QtBot
) -> None:
    window, editor = form
    window.setProperty(
        "schema",
        [
            {"key": "level", "label": "Level", "kind": "text", "readOnly": True},
            {"key": "description", "label": "Description", "kind": "multiline", "enabled": False},
        ],
    )
    window.setProperty("snapshot", {"level": "1.2", "description": "Original"})
    window.setProperty("validation", {"level": "Enter a valid level"})
    qapp.processEvents()
    level = visual_item(editor, "fieldInput_0")
    description = visual_item(editor, "fieldInput_1")
    assert level.property("readOnly")
    assert not description.property("enabled")
    error = visual_item(editor, "fieldError_0")
    assert error.property("visible")
    assert error.property("text") == "Enter a valid level"
    accessible = QAccessible.queryAccessibleInterface(level)
    assert accessible.text(QAccessible.Text.Name) == "Level"
    assert accessible.text(QAccessible.Text.Description) == "Enter a valid level"
    edits: list[tuple[str, object]] = []
    editor.fieldEdited.connect(lambda key, value: edits.append((key, value)))
    window.setProperty("snapshot", {"level": "2.3", "description": "Externally changed"})
    qapp.processEvents()
    assert level.property("text") == "2.3"
    assert description.property("text") == "Externally changed"
    assert not edits
    level.forceActiveFocus()
    qtbot.keyClick(window, Qt.Key.Key_9)
    assert not edits
    assert level.property("text") == "2.3"

"""Standalone QML document actions: host-owned state and intent-only UI."""

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from pytestqt.qtbot import QtBot


@pytest.fixture
def actions(qtbot: QtBot) -> QObject:
    engine = QQmlEngine()
    qml_file = Path(__file__).resolve().parents[1] / "qml" / "DocumentManagementActions.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_file)))
    assert component.isReady(), [error.toString() for error in component.errors()]
    root = component.create()
    assert root is not None, [error.toString() for error in component.errors()]
    root.setProperty("width", 500)
    yield root
    root.deleteLater()
    engine.deleteLater()


def button(actions: QObject, name: str) -> QObject:
    found = actions.findChild(QObject, name)
    assert found is not None
    assert found.property("activeFocusOnTab") is True
    assert found.property("text")
    return found


def test_project_and_selection_gate_actions(actions: QObject) -> None:
    names = ("addDocumentAction", "removeDocumentAction", "reviewAllAction", "clearLinksAction", "reorderLevelsAction")
    assert [button(actions, name).property("enabled") for name in names] == [False] * 5

    actions.setProperty("projectAvailable", True)
    assert [button(actions, name).property("enabled") for name in names] == [True, False, False, False, False]

    actions.setProperty("selectedPrefix", "REQ")
    assert [button(actions, name).property("enabled") for name in names] == [True, True, True, True, False]
    actions.setProperty("reorderAvailable", True)
    assert button(actions, "reorderLevelsAction").property("enabled") is True

    actions.setProperty("childPrefixes", ["CHILD", "CHILD-2"])
    assert button(actions, "removeDocumentAction").property("enabled") is False
    warning = actions.findChild(QObject, "childDocumentsWarning")
    assert warning is not None and warning.property("visible") is True
    assert "CHILD" in warning.property("text")
    assert button(actions, "reviewAllAction").property("enabled") is True

    actions.setProperty("projectAvailable", False)
    assert [button(actions, name).property("enabled") for name in names] == [False] * 5


def test_host_receives_only_intents_and_deletion_is_guarded(actions: QObject) -> None:
    seen: list[tuple[str, str]] = []
    signals = {
        "addDocumentAction": "addDocumentRequested",
        "removeDocumentAction": "removeDocumentRequested",
        "reviewAllAction": "reviewAllRequested",
        "clearLinksAction": "clearLinksRequested",
        "reorderLevelsAction": "reorderLevelsRequested",
    }
    for name, signal in signals.items():
        getattr(actions, signal).connect(lambda prefix, signal=signal: seen.append((signal, prefix)))

    actions.setProperty("projectAvailable", True)
    button(actions, "addDocumentAction").clicked.emit()
    assert seen == [("addDocumentRequested", "")]

    actions.setProperty("selectedPrefix", "REQ")
    actions.setProperty("parentPrefix", "ROOT")
    actions.setProperty("reorderAvailable", True)
    for name in signals:
        button(actions, name).clicked.emit()
    assert seen[1:] == [
        ("addDocumentRequested", "REQ"),
        ("removeDocumentRequested", "REQ"),
        ("reviewAllRequested", "REQ"),
        ("clearLinksRequested", "REQ"),
        ("reorderLevelsRequested", "REQ"),
    ]

    actions.setProperty("childPrefixes", ["SUB"])
    button(actions, "removeDocumentAction").clicked.emit()
    assert len(seen) == 6
    actions.setProperty("projectAvailable", False)
    for name in signals:
        button(actions, name).clicked.emit()
    assert len(seen) == 6

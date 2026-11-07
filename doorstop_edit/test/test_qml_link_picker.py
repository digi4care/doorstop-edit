"""Standalone LinkPicker contract, using a real Qt Quick component without a backend."""

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtQml import QJSValue, QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def link_host(qapp: QApplication) -> Any:
    engine = QQmlApplicationEngine()
    component = QQmlComponent(engine)
    component.setData(
        b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    visible: true; width: 520; height: 560
    App.LinkPicker { id: picker; objectName: "picker"; anchors.fill: parent.contentItem }
} """,
        QUrl.fromLocalFile(str(Path(__file__).resolve())),
    )
    assert component.isReady(), component.errors()
    window = cast(QQuickWindow, component.create())
    assert window is not None, component.errors()
    picker = window.findChild(QObject, "picker")
    assert picker is not None
    qapp.processEvents()
    yield window, picker
    window.close()
    window.deleteLater()
    component.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def qml_value(value: Any) -> Any:
    return value.toVariant() if isinstance(value, QJSValue) else value


def setup_picker(qapp: QApplication, picker: QObject) -> None:
    picker.setProperty("sourceUid", "REQ-1")
    picker.setProperty(
        "candidateItems",
        [
            {"uid": "REQ-1", "header": "Source"},
            {"uid": "REQ-2", "header": "Second target", "level": "1"},
            {"uid": "REQ-3", "header": "Third target", "valid": False},
            {"uid": "REQ-4", "header": "Fourth target"},
            {"uid": "", "header": "Damaged record"},
        ],
    )
    picker.setProperty(
        "linkedTargets",
        [
            {"uid": "REQ-2", "status": "suspect"},
            {"uid": "LOST-1", "status": "unresolved"},
            {"uid": "REQ-1", "status": "unknown"},
        ],
    )
    qapp.processEvents()


def test_search_keyboard_and_read_only_intents(link_host: Any, qapp: QApplication) -> None:
    window, picker = link_host
    setup_picker(qapp, picker)
    assert [row["uid"] for row in qml_value(picker.property("results"))] == [
        "LOST-1",
        "REQ-1",
        "REQ-2",
        "REQ-3",
        "REQ-4",
    ]
    assert qml_value(picker.property("results"))[2]["status"] == "suspect"
    assert qml_value(picker.property("results"))[0]["available"] is False
    original = picker.property("linkedTargets")
    adds: list[str] = []
    removes: list[str] = []
    picker.addRequested.connect(adds.append)
    picker.removeRequested.connect(removes.append)
    search = window.findChild(QObject, "linkSearch")
    assert search is not None
    picker.focusSearch()
    search.setProperty("text", "second req-2")
    qapp.processEvents()
    assert [row["uid"] for row in qml_value(picker.property("results"))] == ["REQ-2"]
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert removes == ["REQ-2"]
    assert picker.property("linkedTargets") == original  # no optimistic snapshot mutation
    search.setProperty("text", "fourth")
    qapp.processEvents()
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert adds == ["REQ-4"]
    search.setProperty("text", "req")
    qapp.processEvents()
    assert qml_value(picker.property("selectedRow"))["uid"] == "REQ-1"
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Down)
    assert qml_value(picker.property("selectedRow"))["uid"] == "REQ-3"
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert adds == ["REQ-4"]  # invalid candidate cannot be added
    search.setProperty("text", "not-present")
    qapp.processEvents()
    assert qml_value(picker.property("selectedRow")) is None


def test_missing_invalid_and_inspect_gates(link_host: Any, qapp: QApplication) -> None:
    _, picker = link_host
    setup_picker(qapp, picker)
    removes: list[str] = []
    inspects: list[str] = []
    picker.removeRequested.connect(removes.append)
    picker.inspectRequested.connect(inspects.append)
    search = picker.findChild(QObject, "linkSearch")
    inspect = picker.findChild(QObject, "linkInspect")
    assert search is not None and inspect is not None
    picker.setProperty("inspectEnabled", True)
    search.setProperty("text", "lost")
    qapp.processEvents()
    assert inspect.property("enabled") is False
    assert picker.statusText(qml_value(picker.property("selectedRow"))) == "Linked · missing target"
    picker.activateSelection()
    assert removes == ["LOST-1"]
    search.setProperty("text", "req-3")
    qapp.processEvents()
    assert picker.findChild(QObject, "linkChange").property("enabled") is False
    search.setProperty("text", "req-4")
    qapp.processEvents()
    assert inspect.property("enabled") is True
    # The host decides whether to expose and implement inspect/open navigation.
    inspect.clicked.emit()
    assert inspects == ["REQ-4"]
    assert picker.property("linkedTargets")[0]["uid"] == "REQ-2"


def test_invalid_link_and_host_refresh(link_host: Any, qapp: QApplication) -> None:
    _, picker = link_host
    setup_picker(qapp, picker)
    picker.setProperty(
        "linkedTargets",
        [
            {"uid": "REQ-3", "status": "unknown"},
            {"uid": "REQ-2", "status": "suspect"},
        ],
    )
    search = picker.findChild(QObject, "linkSearch")
    assert search is not None
    search.setProperty("text", "req-3")
    qapp.processEvents()
    assert picker.statusText(picker.property("selectedRow")) == "Linked · invalid target"
    removes: list[str] = []
    picker.removeRequested.connect(removes.append)
    picker.activateSelection()
    assert removes == ["REQ-3"]
    assert qml_value(picker.property("selectedRow"))["linked"] is True
    picker.setProperty("linkedTargets", [{"uid": "REQ-2", "status": "ok"}])
    qapp.processEvents()
    assert qml_value(picker.property("selectedRow"))["linked"] is False
    assert picker.statusText(picker.property("selectedRow")) == "Invalid target"
    search.setProperty("text", "req-2")
    qapp.processEvents()
    assert picker.statusText(picker.property("selectedRow")) == "Linked"

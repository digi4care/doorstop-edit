"""Focused Qt Quick accessibility contract checks for standalone QML views.

These tests inspect Qt's accessible names and exercise keyboard focus in real
components. They do not verify screen-reader speech, translated catalogs,
contrast, text scaling, or platform preference propagation; those need manual
checks in the target environments.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

# The real RenderPreview instantiates WebEngineView; initialize before qapp.
QtWebEngineQuick.initialize()


def accessible_name(item: QObject) -> str:
    interface = QAccessible.queryAccessibleInterface(item)
    assert interface is not None, f"No Qt accessibility interface for {item.objectName()}"
    return interface.text(QAccessible.Text.Name)


@pytest.fixture
def component_host(qapp: QApplication, qtbot: QtBot) -> Iterator[Callable[[str], QQuickWindow]]:
    created: list[tuple[QQmlEngine, QQmlComponent, QQuickWindow]] = []

    def create(body: str) -> QQuickWindow:
        engine = QQmlEngine()
        engine.rootContext().setContextProperty("backend", {"selectedItem": {}, "projectRoot": ""})
        component = QQmlComponent(engine)
        component.setData(
            (
                "import QtQuick 2.15\n"
                "import QtQuick.Controls 2.15\n"
                'import "../qml" as App\n'
                "ApplicationWindow { visible: true; width: 850; height: 780\n" + body + "\n}"
            ).encode(),
            QUrl.fromLocalFile(str(Path(__file__).resolve())),
        )
        assert component.isReady(), component.errors()
        window = component.create()
        assert isinstance(window, QQuickWindow), component.errors()
        created.append((engine, component, window))
        qtbot.waitUntil(window.isActive)
        return window

    yield create
    for engine, component, window in reversed(created):
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def named(window: QQuickWindow, object_name: str) -> QQuickItem:
    item = window.findChild(QQuickItem, object_name)
    assert item is not None, object_name
    return item


def visible_items(window: QQuickWindow, object_name: str) -> list[QQuickItem]:
    def walk(item: QQuickItem) -> Iterator[QQuickItem]:
        for child in item.childItems():
            if child.objectName() == object_name and child.isVisible():
                yield child
            yield from walk(child)

    return list(walk(window.contentItem()))


def test_graph_names_and_result_keyboard_navigation(
    component_host: Callable[[str], QQuickWindow], qtbot: QtBot
) -> None:
    window = component_host('App.GraphExplorer { objectName: "graph"; anchors.fill: parent }')
    graph = named(window, "graph")
    graph.setProperty(
        "graph",
        {
            "projectId": "demo",
            "nodes": [
                {"id": "document:REQ", "type": "Document", "prefix": "REQ", "provenance": {}},
                {"id": "document:SPEC", "type": "Document", "prefix": "SPEC", "provenance": {}},
            ],
            "edges": [],
        },
    )
    graph.setProperty("active", True)
    graph.rebuild()
    qtbot.waitUntil(lambda: len(visible_items(window, "graphResultRow")) == 2)

    search = named(window, "graphSearchField")
    results = named(window, "graphResultsList")
    assert accessible_name(search) == "Search graph by UID, header, document or finding"
    assert "Up and Down select" in accessible_name(results)
    assert accessible_name(named(window, "graphCloseButton")) == "Close graph and return to document and item editor"
    assert accessible_name(named(window, "graphZoomIn")) == "Zoom in graph"
    assert accessible_name(named(window, "graphViewport")).startswith("Graph map.")
    assert {accessible_name(row) for row in visible_items(window, "graphResultRow")} == {
        "REQ, Document",
        "SPEC, Document",
    }
    assert {accessible_name(card) for card in visible_items(window, "graphNodeCard")} >= {"REQ, Document, Selected"}

    search.forceActiveFocus()
    qtbot.waitUntil(lambda: search.hasActiveFocus())
    QTest.keyClick(window, Qt.Key.Key_Down)
    qtbot.waitUntil(lambda: results.hasActiveFocus())
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: "SPEC, Document, Selected" in {accessible_name(card) for card in visible_items(window, "graphNodeCard")}
    )
    assert results.hasActiveFocus()


def test_preview_names_and_tab_focus(component_host: Callable[[str], QQuickWindow], qtbot: QtBot) -> None:
    window = component_host("""QtObject {
        id: bridge
        property string pageHtml: "<p>Preview fixture</p>"
        property url baseUrl: "about:blank"
        property string viewMode: "document"
        property bool running: false
        property int progress: 0
        property string errorMessage: ""
        signal htmlUpdateItem(string id, string content, bool focus, bool hide)
        signal htmlSelectItem(string id)
        signal pageChanged()
        function loadSucceeded() {}
        function loadFailed(message) {}
        function openExternal(url) {}
        function reload() {}
        function bridgeReady(generation) {}
        function open_item(uid) {}
    }
    App.RenderPreview { anchors.fill: parent; renderBridge: bridge }""")
    mode = named(window, "renderModePicker")
    reload_button = named(window, "renderReloadButton")
    search = named(window, "renderSearchField")
    # Real WebEngineView, not a replacement control. Qt's offscreen accessibility
    # interface returns an empty name for this view; its announcement is manual.
    named(window, "renderWebView")
    assert accessible_name(mode) == "Preview mode"
    assert accessible_name(reload_button) == "Reload preview"
    assert accessible_name(search) == "Find text in preview"

    mode.forceActiveFocus()
    qtbot.waitUntil(mode.hasActiveFocus)
    QTest.keyClick(window, Qt.Key.Key_Tab)
    qtbot.waitUntil(reload_button.hasActiveFocus)
    QTest.keyClick(window, Qt.Key.Key_Tab)
    qtbot.waitUntil(search.hasActiveFocus)


def test_settings_names_initial_focus_and_escape(component_host: Callable[[str], QQuickWindow], qtbot: QtBot) -> None:
    window = component_host('App.SettingsDialog { objectName: "settings"; Component.onCompleted: open() }')
    close_button = named(window, "settingsCloseButton")
    qtbot.waitUntil(close_button.hasActiveFocus)
    assert accessible_name(close_button) == "Close settings"
    for object_name, expected in (
        ("colorProfileSelector", "Color profile"),
        ("fontSizeSpinBox", "Font size"),
        ("densitySpinBox", "Density"),
        ("spellcheckSwitch", "Check spelling"),
        ("spellingLanguageSelector", "Spelling language"),
    ):
        assert accessible_name(named(window, object_name)) == expected

    QTest.keyClick(window, Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: accessible_name(window.activeFocusItem()) == "Night theme mode")
    QTest.keyClick(window, Qt.Key.Key_Escape)
    dialog = window.findChild(QObject, "settings")
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.property("visible"))

"""Isolated QML fixture for the unintegrated workspace panel component."""

from pathlib import Path
from typing import Any, Iterator, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


@pytest.fixture
def workspace(qapp: QApplication, qtbot: QtBot) -> Iterator[tuple[QQuickWindow, Any]]:
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(
        b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    id: host
    visible: true; width: 1180; height: 720
    property int workspaceWidth: 1180
    App.WorkspacePanels {
        id: panels; objectName: "workspacePanels"
        width: host.workspaceWidth; height: parent.height
        documentContent: Rectangle { objectName: "documentFixture"; color: "red" }
        itemContent: Rectangle { objectName: "itemFixture"; color: "green" }
        editorContent: TextField { objectName: "draftFixture"; text: "unsaved draft" }
        pinnedContent: Rectangle { objectName: "pinnedFixture"; color: "blue" }
    }
}
""",
        QUrl.fromLocalFile(str(Path(__file__).resolve())),
    )
    assert component.isReady(), component.errors()
    window = component.create()
    assert isinstance(window, QQuickWindow), component.errors()
    qtbot.waitUntil(lambda: cast(Any, window.findChild(QObject, "draftFixture")) is not None)
    panels = cast(Any, window.findChild(QObject, "workspacePanels"))
    assert panels is not None
    yield window, panels
    window.close()
    window.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_loaded_contents_survive_visibility_changes(workspace: tuple[QQuickWindow, Any]) -> None:
    window, panels = workspace
    draft = cast(Any, window.findChild(QObject, "draftFixture"))
    assert draft.property("text") == "unsaved draft"
    assert panels.property("currentPanel") == "editor"
    assert not panels.property("pinnedVisible")

    panels.setPanelVisible("editor", False)
    assert panels.property("currentPanel") == "items"
    assert cast(Any, window.findChild(QObject, "draftFixture")) is draft
    panels.setPanelVisible("pinned", True)
    assert panels.property("currentPanel") == "pinned"
    assert cast(Any, window.findChild(QObject, "pinnedFixture")) is not None
    panels.setPanelVisible("editor", True)
    assert draft.property("text") == "unsaved draft"
    assert panels.property("currentPanel") == "editor"


def test_split_sizes_and_orientation_contract(workspace: tuple[QQuickWindow, Any], qtbot: QtBot) -> None:
    window, panels = workspace
    documents = cast(Any, window.findChild(QObject, "documentsPane"))
    assert panels.property("horizontal")
    assert documents.property("width") >= 180
    spy = QSignalSpy(panels.splitterSizesCommitted)
    panels.captureSizes()
    assert spy.count() == 1
    assert panels.property("documentsWidth") == pytest.approx(documents.property("width"))

    window.showMaximized()  # Exercise the case where offscreen ignores window.resize().
    qtbot.waitUntil(lambda: window.visibility() == QQuickWindow.Visibility.Maximized)
    assert window.width() > 740
    window.setProperty("workspaceWidth", 740)
    qtbot.waitUntil(lambda: panels.property("width") == 740 and not panels.property("horizontal"))
    # Orientation flips before SplitView has finished laying out its children.
    qtbot.waitUntil(lambda: documents.property("height") >= 95, timeout=3000)
    panels.captureSizes()
    assert panels.property("documentsHeight") == pytest.approx(documents.property("height"))
    assert panels.property("documentsHeight") >= 95
    assert spy.count() == 2


def test_toolbar_controls_toggle_hidden_panel(workspace: tuple[QQuickWindow, Any], qtbot: QtBot) -> None:
    window, panels = workspace
    button = cast(Any, window.findChild(QObject, "pinnedToggle"))
    assert button is not None
    assert not panels.property("pinnedVisible")
    center = button.mapToScene(QPointF(button.property("width") / 2, button.property("height") / 2))
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(round(center.x()), round(center.y())),
    )
    qtbot.waitUntil(lambda: panels.property("pinnedVisible"))
    assert panels.property("currentPanel") == "pinned"


def test_dragging_splitter_commits_size(workspace: tuple[QQuickWindow, Any], qtbot: QtBot) -> None:
    window, panels = workspace
    split = cast(QQuickItem, window.findChild(QQuickItem, "workspaceSplitView"))
    documents = cast(QQuickItem, window.findChild(QQuickItem, "documentsPane"))
    handle = next(
        child for child in split.childItems() if child.isVisible() and child.width() == 9 and child.height() > 100
    )
    initial_width = documents.width()
    spy = QSignalSpy(panels.splitterSizesCommitted)
    center = handle.mapToScene(QPointF(handle.width() / 2, handle.height() / 2))
    origin = QPoint(round(center.x()), round(center.y()))
    moved = QPoint(origin.x() + 32, origin.y())
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, origin)
    QTest.mouseMove(window, moved)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, moved)
    qtbot.waitUntil(lambda: spy.count() > 0)
    assert documents.width() > initial_width
    assert panels.property("documentsWidth") == pytest.approx(documents.width())
    panels.setProperty("documentsWidth", 260)
    qtbot.waitUntil(lambda: documents.width() == pytest.approx(260))


def test_panel_state_round_trip(workspace: tuple[QQuickWindow, Any]) -> None:
    _, panels = workspace
    state = panels.capturePanelState().toVariant()
    assert type(state) is dict
    assert all(type(value) in (int, float, bool, str) for value in state.values())
    assert state["version"] == 1
    changed = dict(
        state,
        documentsVisible=False,
        itemsVisible=False,
        editorVisible=True,
        pinnedVisible=True,
        currentPanel="pinned",
        documentsWidth=201,
        itemsWidth=222,
        editorWidth=333,
        pinnedWidth=244,
        documentsHeight=111,
        itemsHeight=122,
        editorHeight=177,
        pinnedHeight=133,
    )
    assert panels.restorePanelState(changed)
    assert panels.restorePanelState(panels.capturePanelState())
    restored = panels.capturePanelState().toVariant()
    for key in changed:
        assert restored[key] == changed[key]


def test_panel_state_rejects_invalid_input_without_mutation(
    workspace: tuple[QQuickWindow, Any],
) -> None:
    _, panels = workspace
    original = panels.capturePanelState().toVariant()
    invalid = dict(original, version=2)
    assert not panels.restorePanelState(invalid)
    malformed = dict(original, editorWidth="wide")
    assert not panels.restorePanelState(malformed)
    assert panels.capturePanelState().toVariant() == original


def test_panel_state_clamps_minimum_sizes(workspace: tuple[QQuickWindow, Any]) -> None:
    _, panels = workspace
    state = panels.capturePanelState().toVariant()
    for key in (
        "documentsWidth",
        "itemsWidth",
        "editorWidth",
        "pinnedWidth",
        "documentsHeight",
        "itemsHeight",
        "editorHeight",
        "pinnedHeight",
    ):
        state[key] = 1
    assert panels.restorePanelState(state)
    sizes = panels.capturePanelState().toVariant()
    assert [sizes[k] for k in ("documentsWidth", "itemsWidth", "editorWidth", "pinnedWidth")] == [180, 210, 300, 190]
    assert [sizes[k] for k in ("documentsHeight", "itemsHeight", "editorHeight", "pinnedHeight")] == [95, 115, 160, 100]

"""Standalone review/diff controls: host state and intent-only behavior."""

from pathlib import Path
from typing import Iterator

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


@pytest.fixture
def controls(qapp: QApplication, qtbot: QtBot) -> Iterator[tuple[QQuickView, QQuickItem]]:
    # Embedding mirrors the application: the host owns the viewport, rather
    # than relying on QQuickView to resize the panel's initial 420x80 root.
    qml_dir = Path(__file__).resolve().parents[1] / "qml"
    base_url = QUrl.fromLocalFile(str(qml_dir / "ReviewDiffHost.qml"))
    view = QQuickView()
    component = QQmlComponent(view.engine())
    component.setData(
        b"""import QtQuick 2.15
import "." as App
Rectangle {
    width: 500; height: 650
    App.ReviewDiffControls {
        objectName: "reviewDiffControls"
        anchors.fill: parent
    }
}""",
        base_url,
    )
    assert component.isReady(), component.errors()
    host = component.create()
    assert isinstance(host, QQuickItem), component.errors()
    view.setContent(base_url, component, host)
    assert not view.errors(), view.errors()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(500, 650)
    view.show()
    qtbot.waitExposed(view)
    root = host.findChild(QQuickItem, "reviewDiffControls")
    assert isinstance(root, QQuickItem)
    qtbot.waitUntil(lambda: root.width() == 500 and root.height() == 650)
    yield view, root
    view.close()
    view.deleteLater()


def child(root: QQuickItem, name: str) -> QObject:
    result = root.findChild(QObject, name)
    assert result is not None, name
    return result


def click(view: QQuickView, button: QObject, qtbot: QtBot) -> None:
    assert button.property("enabled") and button.property("visible")
    assert isinstance(button, QQuickItem)
    root = view.rootObject()
    assert isinstance(root, QQuickItem)

    def target_is_uncovered() -> bool:
        # Qt Quick's Flow/RowLayout positions children in a later polish pass.
        # An enabled button can still overlap a sibling while that pass is pending.
        center = button.mapToScene(button.boundingRect().center())
        parent = button.parentItem()
        return (
            0 <= center.x() < view.width()
            and 0 <= center.y() < view.height()
            and root.contains(root.mapFromScene(center))
            and parent is not None
            and all(
                sibling is button
                or not sibling.isVisible()
                or not sibling.mapRectToScene(sibling.boundingRect()).contains(center)
                for sibling in parent.childItems()
            )
        )

    qtbot.waitUntil(target_is_uncovered)
    center = button.mapToScene(button.boundingRect().center())
    pos = QPoint(int(center.x()), int(center.y()))
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=pos)
    grab = view.mouseGrabberItem()
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=pos)
    assert grab == button, f"Pointer hit {grab}, expected {button.objectName()} at {center}"


def test_review_and_clear_are_host_intents(controls: tuple[QQuickView, QQuickItem], qtbot: QtBot) -> None:
    view, root = controls
    events: list[str] = []
    root.__getattribute__("reviewRequested").connect(lambda: events.append("review"))
    root.__getattribute__("unreviewRequested").connect(lambda: events.append("unreview"))
    root.__getattribute__("clearSuspectsRequested").connect(lambda: events.append("clear"))
    root.__getattribute__("diffRequested").connect(lambda: events.append("diff"))
    review = child(root, "reviewAction")
    unreview = child(root, "unreviewAction")
    clear = child(root, "clearSuspectsAction")
    diff = child(root, "diffAction")
    assert child(root, "reviewStatus").property("text") == "No item selected"
    assert not any(button.property("enabled") for button in (review, unreview, clear, diff))

    root.setProperty("hasItem", True)
    root.setProperty("cleared", False)
    root.setProperty("canDiff", True)
    root.setProperty("canUnreview", True)
    assert child(root, "reviewStatus").property("text") == "Not reviewed"
    assert review.property("enabled") and not unreview.property("enabled")
    click(view, review, qtbot)
    click(view, clear, qtbot)
    click(view, diff, qtbot)
    assert events == ["review", "clear", "diff"]
    # No local optimistic mutation: the host must supply a new fingerprint verdict.
    assert not root.property("reviewed") and not root.property("cleared")
    root.setProperty("reviewed", True)
    root.setProperty("cleared", True)
    assert child(root, "reviewStatus").property("text") == "Reviewed"
    assert not review.property("enabled") and not clear.property("enabled")
    click(view, unreview, qtbot)
    assert events[-1] == "unreview"
    assert root.property("reviewed")
    root.setProperty("canUnreview", False)
    assert not unreview.property("visible")
    root.setProperty("hasItem", False)
    assert not diff.property("enabled")


def test_diff_is_supplied_and_history_is_bounded(controls: tuple[QQuickView, QQuickItem], qtbot: QtBot) -> None:
    view, root = controls
    modes: list[str] = []
    revisions: list[int] = []
    root.__getattribute__("diffModeRequested").connect(modes.append)
    root.__getattribute__("diffRevisionRequested").connect(revisions.append)
    root.setProperty("hasItem", True)
    root.setProperty("canDiff", True)
    root.setProperty("diffVisible", True)
    QApplication.processEvents()
    # The host explicitly gives the panel its viewport before interaction.
    assert root.width() == view.width() and root.height() == view.height()
    qtbot.waitUntil(lambda: root.implicitHeight() > 80)
    message = child(root, "diffMessage")
    assert message.property("text") == "Select a comparison"
    root.setProperty("diffState", "loading")
    assert message.property("text") == "Loading changes…"
    root.setProperty("diffState", "error")
    root.setProperty("diffError", "Git unavailable")
    assert message.property("text") == "Git unavailable"
    root.setProperty("diffState", "ready")
    assert message.property("text") == "No changes"
    root.setProperty("diffText", "-old\n+new")
    assert child(root, "diffContent").property("text") == "-old\n+new"

    picker = child(root, "diffModePicker")
    # Selecting a mode requests it; the host must resolve and publish it.
    assert isinstance(picker, QQuickItem)
    QApplication.processEvents()
    picker.forceActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Down)
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.keyClick(view, Qt.Key.Key_Escape)  # Close the picker popup before clicking history.
    QApplication.processEvents()
    assert modes == ["git"] and root.property("diffMode") == "file"
    root.setProperty("diffMode", "git")
    root.setProperty("historyCount", 3)
    older = child(root, "olderDiffAction")
    newer = child(root, "newerDiffAction")
    assert older.property("enabled") and not newer.property("enabled")
    assert isinstance(older, QQuickItem)
    qtbot.waitUntil(
        lambda: (
            older.mapToScene(older.boundingRect().center()).y()
            > picker.mapToScene(picker.boundingRect().center()).y() + picker.height() / 2
            and root.implicitHeight() >= older.mapToScene(older.boundingRect().center()).y() + older.height() / 2
        )
    )
    click(view, older, qtbot)
    assert revisions == [1] and root.property("historyIndex") == 0
    root.setProperty("historyIndex", 2)
    assert not older.property("enabled") and newer.property("enabled")
    click(view, newer, qtbot)
    assert revisions == [1, 1]
    root.setProperty("diffState", "loading")
    assert not older.property("enabled") and not newer.property("enabled")
    root.setProperty("hasItem", False)
    assert not picker.property("visible") or not picker.property("enabled")

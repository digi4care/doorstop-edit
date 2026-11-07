"""Standalone context-menu contract; the host handles every request."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, Qt, QUrl
from PySide6.QtGui import QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def menu_window(qapp: QApplication) -> Iterator[tuple[QWindow, QObject]]:
    engine = QQmlApplicationEngine()
    base_url = QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "TreeActionsHarness.qml"))
    engine.loadData(
        b"""import QtQuick 2.15
import QtQuick.Controls 2.15
Window {
    visible: true
    width: 320
    height: 240
    TreeContextActions { objectName: "treeActions" }
}
""",
        base_url,
    )
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    assert isinstance(window, QWindow)
    menu = window.findChild(QObject, "treeActions")
    assert menu is not None
    yield window, menu
    window.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def open_menu(qapp: QApplication, menu: QObject) -> None:
    assert QMetaObject.invokeMethod(menu, "popup")
    qapp.processEvents()
    assert menu.property("visible")


def action(menu: QObject, name: str) -> QObject:
    result = menu.findChild(QObject, name)
    assert result is not None
    return result


def click(qapp: QApplication, menu: QObject, name: str) -> None:
    target = action(menu, name)
    assert target.property("visible") and target.property("enabled")
    assert QMetaObject.invokeMethod(target, "click")
    qapp.processEvents()


def test_background_and_item_intents_are_targeted(menu_window: tuple[QWindow, QObject], qapp: QApplication) -> None:
    _, menu = menu_window
    events: list[tuple[str, object]] = []
    for signal_name in (
        "createItemRequested",
        "deleteItemRequested",
        "pinItemRequested",
        "popupItemRequested",
        "showInactiveRequested",
        "reloadTreeRequested",
        "expandAllRequested",
        "collapseAllRequested",
    ):
        getattr(cast(Any, menu), signal_name).connect(lambda *args, name=signal_name: events.append((name, args)))

    menu.setProperty("projectAvailable", True)
    menu.setProperty("previewAvailable", True)
    open_menu(qapp, menu)
    assert not action(menu, "deleteItemAction").property("visible")
    assert action(menu, "showInactiveAction").property("text") == "Show Inactive"
    click(qapp, menu, "createItemAction")
    assert events[-1] == ("createItemRequested", ("",))

    menu.setProperty("contextType", "item")
    menu.setProperty("itemUid", "REQ-001")
    for name, expected in (
        ("createItemAction", ("createItemRequested", ("REQ-001",))),
        ("deleteItemAction", ("deleteItemRequested", ("REQ-001",))),
        ("pinItemAction", ("pinItemRequested", ("REQ-001",))),
        ("popupItemAction", ("popupItemRequested", ("REQ-001",))),
        ("showInactiveAction", ("showInactiveRequested", (True,))),
        ("reloadTreeAction", ("reloadTreeRequested", ())),
        ("expandAllAction", ("expandAllRequested", ())),
        ("collapseAllAction", ("collapseAllRequested", ())),
    ):
        open_menu(qapp, menu)
        click(qapp, menu, name)
        assert events[-1] == expected
    menu.setProperty("showInactive", True)
    open_menu(qapp, menu)
    assert action(menu, "showInactiveAction").property("text") == "Hide Inactive"
    click(qapp, menu, "showInactiveAction")
    assert events[-1] == ("showInactiveRequested", (False,))


def test_invalid_and_missing_item_targets_do_not_offer_mutations(
    menu_window: tuple[QWindow, QObject], qapp: QApplication
) -> None:
    _, menu = menu_window
    menu.setProperty("contextType", "item")
    menu.setProperty("projectAvailable", True)
    menu.setProperty("previewAvailable", True)
    for uid, invalid in (("REQ-001", True), ("", False)):
        menu.setProperty("itemUid", uid)
        menu.setProperty("invalidItem", invalid)
        open_menu(qapp, menu)
        for name in ("createItemAction", "deleteItemAction", "pinItemAction", "popupItemAction"):
            target = action(menu, name)
            assert not (target.property("visible") and target.property("enabled"))
        assert action(menu, "reloadTreeAction").property("enabled")
        QMetaObject.invokeMethod(menu, "close")
    menu.setProperty("contextType", "background")
    menu.setProperty("invalidItem", False)
    menu.setProperty("projectAvailable", False)
    open_menu(qapp, menu)
    assert not action(menu, "createItemAction").property("enabled")
    assert not action(menu, "reloadTreeAction").property("enabled")


def test_document_only_offers_existing_preview_intent(menu_window: tuple[QWindow, QObject], qapp: QApplication) -> None:
    _, menu = menu_window
    requested: list[str] = []
    cast(Any, menu).popupDocumentRequested.connect(requested.append)
    menu.setProperty("contextType", "document")
    menu.setProperty("documentPrefix", "REQ")
    menu.setProperty("projectAvailable", True)
    menu.setProperty("previewAvailable", False)
    open_menu(qapp, menu)
    for name in ("createItemAction", "deleteItemAction", "pinItemAction", "popupItemAction", "reloadTreeAction"):
        assert not action(menu, name).property("visible")
    preview = action(menu, "popupDocumentAction")
    assert preview.property("visible") and not preview.property("enabled")
    menu.setProperty("previewAvailable", True)
    assert preview.property("enabled")
    click(qapp, menu, "popupDocumentAction")
    assert requested == ["REQ"]
    menu.setProperty("documentPrefix", "")
    open_menu(qapp, menu)
    assert not action(menu, "popupDocumentAction").property("visible")


def test_menu_supports_keyboard_activation_and_escape(menu_window: tuple[QWindow, QObject], qapp: QApplication) -> None:
    window, menu = menu_window
    requested: list[str] = []
    cast(Any, menu).createItemRequested.connect(requested.append)
    menu.setProperty("contextType", "item")
    menu.setProperty("itemUid", "REQ-002")
    menu.setProperty("projectAvailable", True)
    open_menu(qapp, menu)
    QTest.keyClick(window, Qt.Key.Key_Down)
    qapp.processEvents()
    assert menu.property("currentIndex") == 0
    QTest.keyClick(window, Qt.Key.Key_Return)
    qapp.processEvents()
    assert requested == ["REQ-002"]
    assert not menu.property("visible")
    open_menu(qapp, menu)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert not menu.property("visible")

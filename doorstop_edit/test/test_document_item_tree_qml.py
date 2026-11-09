"""Standalone presentation contract for the document/item tree (no backend)."""

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

TREE = Path(__file__).parents[1] / "qml" / "DocumentItemTree.qml"


@pytest.fixture
def tree(qapp: QApplication) -> Any:
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(TREE)))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    view.resize(680, 520)
    view.show()
    root = view.rootObject()
    assert root is not None
    yield view, root
    view.close()
    view.deleteLater()
    qapp.processEvents()


def control(root: QQuickItem, name: str) -> QObject:
    found = root.findChild(QObject, name)
    assert found is not None
    return found


def rows(root: QQuickItem) -> list[dict[str, Any]]:
    value = root.property("visibleRows")
    return cast(list[dict[str, Any]], value.toVariant() if hasattr(value, "toVariant") else value)


def sample() -> dict[str, Any]:
    return {
        "documents": [
            {
                "prefix": "REQ",
                "items": [
                    {
                        "uid": "REQ-3",
                        "level": "2.1",
                        "header": "Safety child",
                        "text": "Critical brake",
                        "active": True,
                    },
                    {
                        "uid": "REQ-1",
                        "level": "2.0",
                        "header": "Safety",
                        "text": "Section title\nDetails",
                        "reviewed": False,
                        "active": True,
                        "normative": False,
                    },
                    {
                        "uid": "REQ-2",
                        "level": "2.2",
                        "header": "Hidden brake",
                        "active": False,
                        "cleared": False,
                        "normative": True,
                    },
                    {
                        "uid": "REQ-4",
                        "level": "4",
                        "header": "Approved",
                        "active": True,
                        "normative": True,
                        "cleared": False,
                        "findings": [{"severity": "error", "message": "Broken"}],
                    },
                    {"uid": "REQ-5", "level": "5", "loadError": "Invalid YAML"},
                ],
            },
            {
                "prefix": "TEST",
                "parentPrefix": "REQ",
                "items": [{"uid": "TEST-1", "level": "1", "header": "Verification", "active": True}],
            },
        ]
    }


def test_hierarchy_filter_inactive_and_snapshot_refresh(tree: Any, qtbot: QtBot) -> None:
    _, root = tree
    source = sample()
    root.setProperty("snapshot", source)
    assert [(r["id"], r["depth"]) for r in rows(root)] == [
        ("document:REQ", 0),
        ("item:REQ:REQ-1", 1),
        ("item:REQ:REQ-3", 2),
        ("item:REQ:REQ-4", 1),
        ("item:REQ:REQ-5", 1),
        ("document:TEST", 1),
        ("item:TEST:TEST-1", 2),
    ]
    assert source["documents"][0]["items"][0]["uid"] == "REQ-3"
    search = control(root, "treeSearch")
    search.setProperty("text", "brake req-3")
    assert [(r["uid"], r["depth"]) for r in rows(root) if r["type"] == "item"] == [("REQ-3", 1)]
    search.setProperty("text", "brake hidden")
    assert not any(r["type"] == "item" for r in rows(root))
    root.setProperty("showInactive", True)
    assert [r["uid"] for r in rows(root) if r["type"] == "item"] == ["REQ-2"]
    search.setProperty("text", "")
    assert any(r["uid"] == "REQ-2" for r in rows(root) if r["type"] == "item")
    source["documents"][0]["items"][0]["header"] = "Changed without publishing"
    assert any(r.get("header") == "Safety child" for r in rows(root))
    next_snapshot = sample()
    next_snapshot["documents"][0]["items"][0]["header"] = "Updated safety child"
    root.setProperty("snapshot", next_snapshot)  # only a newly published snapshot triggers rebuild
    qtbot.waitUntil(lambda: any(r.get("header") == "Updated safety child" for r in rows(root)))


def test_status_separation_and_selection_intents(tree: Any, qtbot: QtBot) -> None:
    view, root = tree
    root.setProperty("snapshot", sample())
    assert root.statusText(rows(root)[1]) == "Needs review · Informative"
    assert root.statusText(next(r for r in rows(root) if r.get("uid") == "REQ-4")) == (
        "Validation error · Suspect links · Normative"
    )
    assert rows(root)[1]["reviewed"] is False
    assert root.displayHeader(rows(root)[1]) == "Section title"
    assert root.statusText(next(r for r in rows(root) if r.get("uid") == "REQ-5")) == "Unable to load item"
    docs: list[str] = []
    items: list[tuple[str, str]] = []
    refreshes: list[bool] = []
    root.documentSelectionRequested.connect(lambda prefix: docs.append(prefix))
    root.itemSelectionRequested.connect(lambda uid, prefix: items.append((uid, prefix)))
    root.refreshRequested.connect(lambda: refreshes.append(True))
    cast(Any, control(root, "treeRefresh")).clicked.emit()
    assert refreshes == [True]
    assert len(rows(root)) == 7  # refresh intent does not reload or mutate the snapshot
    listing = control(root, "treeRows")
    listing.setProperty("currentIndex", 0)
    cast(QQuickItem, listing).forceActiveFocus()
    qtbot.waitUntil(lambda: view.activeFocusItem() in (listing, listing.property("currentItem")))
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert docs == ["REQ"]
    listing.setProperty("currentIndex", 1)
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert items == [("REQ-1", "REQ")]
    assert root.property("selectedItemUid") == ""  # host must confirm selection
    root.setProperty("selectedDocumentPrefix", "REQ")
    root.setProperty("selectedItemUid", "REQ-1")
    assert root.property("selectedItemUid") == "REQ-1"


def test_expand_collapse_preserves_search_visibility(tree: Any) -> None:
    _, root = tree
    root.setProperty("snapshot", sample())
    root.setAllExpanded(False)
    assert [r["id"] for r in rows(root)] == ["document:REQ"]
    root.setExpanded("document:REQ", True)
    assert [r["id"] for r in rows(root)] == [
        "document:REQ",
        "item:REQ:REQ-1",
        "item:REQ:REQ-4",
        "item:REQ:REQ-5",
        "document:TEST",
    ]
    control(root, "treeSearch").setProperty("text", "brake req-3")
    assert [r["uid"] for r in rows(root) if r["type"] == "item"] == ["REQ-3"]
    control(root, "treeSearch").setProperty("text", "")
    assert not any(r.get("uid") == "REQ-3" for r in rows(root))
    root.setAllExpanded(True)
    assert any(r.get("uid") == "REQ-3" for r in rows(root))

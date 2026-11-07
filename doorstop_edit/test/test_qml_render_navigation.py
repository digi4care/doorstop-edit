"""Navigation and find-in-page through a live Qt Quick WebEngineView."""

from pathlib import Path
from typing import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from doorstop_edit.qml_backend import QmlBackend
from doorstop_edit.qml_render_bridge import QmlRenderBridge
from tools.gen_sample_tree import generate_tree

QtWebEngineQuick.initialize()


@pytest.fixture
def host(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> Iterator[tuple[QmlBackend, QmlRenderBridge, QQuickWindow]]:
    generate_tree(tmp_path, num_docs=2, num_req=3)
    backend = QmlBackend(root=tmp_path)
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    renderer = QmlRenderBridge(backend)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("previewRenderer", renderer)
    source = b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    id: host
    visible: true; width: 750; height: 480
    property var result: null
    property var popupBridge: null
    function execute(script) {
        mainPreview.webView.runJavaScript(script, function(value) { host.result = value })
    }
    function executePopup(script) {
        popupPreview.webView.runJavaScript(script, function(value) { host.result = value })
    }
    function reloadPage() { mainPreview.webView.reload() }
    App.RenderPreview {
        id: mainPreview; objectName: "renderPreview"
        anchors.left: parent.left; anchors.top: parent.top
        width: parent.width / 2; height: parent.height
        renderBridge: previewRenderer
    }
    App.RenderPreview {
        id: popupPreview; objectName: "popupPreview"
        anchors.right: parent.right; anchors.top: parent.top
        width: parent.width / 2; height: parent.height
        renderBridge: host.popupBridge
    }
}"""
    component = QQmlComponent(engine)
    component.setData(source, QUrl.fromLocalFile(str(Path(__file__).resolve())))
    assert component.isReady(), component.errors()
    window = component.create()
    assert isinstance(window, QQuickWindow), component.errors()
    qtbot.waitUntil(lambda: renderer._channel_ready and renderer.progress == 100, timeout=20000)
    yield backend, renderer, window
    renderer.shutdown()
    backend.shutdown()
    window.close()
    window.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def js(qtbot: QtBot, window: QQuickWindow, script: str, *, popup: bool = False) -> object:
    window.setProperty("result", "__pending__")
    getattr(window, "executePopup" if popup else "execute")(script)
    qtbot.waitUntil(lambda: window.property("result") != "__pending__", timeout=10000)
    return window.property("result")


def wait_for_item_link(qtbot: QtBot, window: QQuickWindow) -> None:
    for _ in range(200):
        window.setProperty("result", "__pending__")
        getattr(window, "execute")("!!document.querySelector('#REQ-A-001 a[onclick]')")
        qtbot.waitUntil(lambda: window.property("result") != "__pending__", timeout=3000)
        if window.property("result"):
            return
        qtbot.wait(100)
    pytest.fail("rendered internal link never became available in WebEngine")


def test_clicked_links_and_popup_routing(
    host: tuple[QmlBackend, QmlRenderBridge, QQuickWindow], qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    backend, renderer, window = host
    opened: list[str] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    popups: list[tuple[QmlRenderBridge, str]] = []

    def record_popup(popup: QmlRenderBridge, title: str) -> None:
        popups.append((popup, title))

    requested: list[tuple[str, str]] = []
    renderer.itemRequested.connect(lambda uid, prefix: requested.append((uid, prefix)))
    renderer.popupCreated.connect(record_popup)
    original = js(qtbot, window, "location.href")
    wait_for_item_link(qtbot, window)
    js(qtbot, window, "document.querySelector('#REQ-A-001 a[onclick]').click(); true")
    qtbot.waitUntil(lambda: len(requested) == 1, timeout=10000)
    assert requested[0][0].startswith("REQ-B-")
    assert requested[0][1] == "REQ-B"
    assert not popups
    assert backend.property("selectedItem")["uid"] == "REQ-A-001"
    assert js(qtbot, window, "location.href") == original

    # Explicit context-menu intent still creates a popup, without changing selection.
    renderer.openPopupItem("REQ-A-001")
    assert len(popups) == 1 and popups[0][0]._pinned_uid == "REQ-A-001"
    popup = popups[0][0]
    window.setProperty("popupBridge", popup)
    qtbot.waitUntil(lambda: popup._channel_ready and popup.progress == 100, timeout=15000)
    nested: list[tuple[QmlRenderBridge, str]] = []
    popup.popupCreated.connect(lambda child, title: nested.append((child, title)))
    popup_original = js(qtbot, window, "location.href", popup=True)
    js(qtbot, window, "document.querySelector('#REQ-A-001 a[onclick]').click(); true", popup=True)
    qtbot.waitUntil(lambda: len(nested) == 1, timeout=10000)
    assert nested[0][0]._pinned_uid.startswith("REQ-B-")
    assert len(popups) == 1  # nested viewer is owned by its popup, not by the primary bridge
    assert len(requested) == 1  # popup links never request current-editor navigation
    assert js(qtbot, window, "location.href", popup=True) == popup_original
    assert backend.property("selectedItem")["uid"] == "REQ-A-001"

    renderer.openPopupDocument("REQ-B")
    assert len(popups) == 2 and popups[1][0]._pinned_uid.startswith("REQ-B-")
    renderer.requestItem("REQ-A-003")
    assert requested[-1] == ("REQ-A-003", "REQ-A")
    # The shell owns current-view mutations and unsaved-draft confirmation.
    assert backend.property("selectedItem")["uid"] == "REQ-A-001"
    js(
        qtbot,
        window,
        "var a=document.createElement('a'); a.href='https://example.test/path'; "
        "document.body.append(a); a.click(); true",
    )
    qtbot.waitUntil(lambda: "https://example.test/path" in opened, timeout=10000)
    assert js(qtbot, window, "location.href") == original
    js(
        qtbot,
        window,
        "var a=document.createElement('a'); a.href='mailto:team@example.test'; "
        "a.target='_blank'; document.body.append(a); a.click(); true",
    )
    qtbot.waitUntil(lambda: "mailto:team@example.test" in opened, timeout=10000)
    assert js(qtbot, window, "location.href") == original
    # Script navigation is not a clicked link and must not replace the WebChannel page.
    js(qtbot, window, "location.href='https://example.test/evil'; true")
    qtbot.wait(300)
    assert js(qtbot, window, "location.href") == original


def test_missing_targets_handler_failure_and_webengine_reload(
    host: tuple[QmlBackend, QmlRenderBridge, QQuickWindow], qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    _backend, renderer, window = host
    original = js(qtbot, window, "location.href")
    js(qtbot, window, "open_item({preventDefault:function(){}}, 'MISSING-001'); true")
    qtbot.waitUntil(lambda: "MISSING-001" in renderer.property("errorMessage"), timeout=10000)
    assert "MISSING-001" in renderer.property("errorMessage")
    renderer.openPopupDocument("MISSING")
    assert "MISSING" in renderer.property("errorMessage")
    opened: list[str] = []

    def fail_url(url: QUrl) -> bool:
        opened.append(url.toString())
        return False

    monkeypatch.setattr(QDesktopServices, "openUrl", fail_url)
    renderer.openExternal("custom-scheme:failure")
    assert opened == ["custom-scheme:failure"]
    js(
        qtbot,
        window,
        "var a=document.createElement('a'); a.href='https://example.test/failure'; "
        "document.body.append(a); a.click(); true",
    )
    qtbot.waitUntil(lambda: "https://example.test/failure" in renderer.property("errorMessage"), timeout=10000)
    assert js(qtbot, window, "location.href") == original
    pages: list[bool] = []
    renderer.pageChanged.connect(lambda: pages.append(True))
    getattr(window, "reloadPage")()
    qtbot.waitUntil(lambda: bool(pages), timeout=15000)
    qtbot.waitUntil(lambda: renderer._channel_ready and renderer.progress == 100, timeout=20000)
    assert js(qtbot, window, "!!document.getElementById('REQ-A-001')")


def test_find_highlight_repeat_clear_and_no_match(
    host: tuple[QmlBackend, QmlRenderBridge, QQuickWindow], qtbot: QtBot
) -> None:
    _backend, renderer, window = host
    preview = window.findChild(QObject, "renderPreview")
    search = window.findChild(QObject, "renderSearchField")
    assert preview is not None and search is not None
    search.setProperty("text", "REQ-A")
    qtbot.waitUntil(lambda: preview.property("searchMatches") >= 3, timeout=10000)
    assert preview.property("searchActiveMatch") >= 1
    first = preview.property("searchActiveMatch")
    # Return triggers findText again without changing the query.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    getattr(search, "forceActiveFocus")()
    QTest.keyClick(window, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: preview.property("searchActiveMatch") != first, timeout=10000)
    search.setProperty("text", "absent-phrase-zz")
    status = window.findChild(QObject, "renderSearchStatus")
    assert status is not None
    qtbot.waitUntil(lambda: status.property("text") == "No matches", timeout=10000)
    assert preview.property("searchMatches") == 0
    search.setProperty("text", "")
    qtbot.waitUntil(lambda: preview.property("searchMatches") == 0 and status.property("text") == "", timeout=10000)
    assert not renderer.property("errorMessage")


def test_main_shell_creates_and_closes_real_popup(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = QmlBackend(root=tmp_path)
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    renderer = QmlRenderBridge(backend)
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda messages: warnings.extend(message.toString() for message in messages))
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("previewRenderer", renderer)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    root = engine.rootObjects()[0]
    assert isinstance(root, QQuickWindow)
    try:
        renderer.openPopupItem("REQ-A-002")
        qtbot.waitUntil(
            lambda: any(w.title().startswith("[REQ-A-002]") for w in QGuiApplication.topLevelWindows()), timeout=10000
        )
        popup = next(w for w in QGuiApplication.topLevelWindows() if w.title().startswith("[REQ-A-002]"))
        qtbot.waitUntil(lambda: bool(renderer._popups) and renderer._popups[0]._channel_ready, timeout=15000)
        assert popup.findChild(QObject, "renderWebView") is not None
        assert backend.property("selectedItem")["uid"] == "REQ-A-001"
        popup.close()
        qtbot.waitUntil(lambda: not renderer._popups, timeout=10000)
        assert not warnings, warnings
    finally:
        root.close()
        renderer.shutdown()
        backend.shutdown()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()

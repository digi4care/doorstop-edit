"""Real Qt Quick WebEngine/WebChannel rendering, not a mocked HTML preview."""

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from doorstop_edit.qml_backend import QmlBackend
from doorstop_edit.qml_render_bridge import QmlRenderBridge
from tools.gen_sample_tree import generate_tree

# Qt Quick WebEngine must be initialized before pytest-qt constructs QApplication.
QtWebEngineQuick.initialize()


def test_worker_html_reaches_qml_webengine_and_webchannel_callback(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = QmlBackend(root=tmp_path)
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    renderer = QmlRenderBridge(backend)
    engine = QQmlApplicationEngine()
    qml_warnings: list[str] = []
    engine.warnings.connect(lambda warnings: qml_warnings.extend(w.toString() for w in warnings))
    engine.rootContext().setContextProperty("previewRenderer", renderer)
    engine.rootContext().setContextProperty("backend", backend)
    # Host the production QML component in a window with JS test probes.
    qml = b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    visible: true; width: 640; height: 440
    property string observedHtml: ""
    function capture() {
        preview.webView.runJavaScript("document.getElementById('REQ-A-001').innerHTML", function(value) {
            observedHtml = value || ""
        })
    }
    function clickInternalLink() {
        preview.webView.runJavaScript("open_item({preventDefault:function(){}}, 'REQ-A-002')")
    }
    function clickExternalLink() {
        preview.webView.runJavaScript("var a = document.createElement('a'); "
                                      + "a.href = 'https://example.test/'; "
                                      + "document.body.appendChild(a); a.click()")
    }
    App.RenderPreview { id: preview; objectName: "renderPreview"; anchors.fill: parent; renderBridge: previewRenderer }
}"""
    window = None
    try:
        component = QQmlComponent(engine)
        component.setData(qml, QUrl.fromLocalFile(str(Path(__file__).resolve())))
        assert component.isReady(), component.errors()
        window = component.create()
        assert isinstance(window, QQuickWindow), component.errors()
        preview = window.findChild(QObject, "renderPreview")
        assert preview is not None
        qtbot.waitUntil(lambda: renderer._render_started, timeout=15000)
        qtbot.waitUntil(lambda: bool(renderer._channel_ready), timeout=15000)
        qtbot.waitUntil(lambda: renderer.progress == 100 or bool(renderer.errorMessage), timeout=30000)
        assert not renderer.errorMessage, f"Markdown rendering failed: {renderer.errorMessage}"

        for _ in range(200):
            getattr(window, "capture")()
            observed_html = str(window.property("observedHtml"))
            if "REQ-A-001" in observed_html and "req-table" in observed_html:
                break
            qtbot.wait(100)
        else:
            pytest.fail(
                "rendered item HTML did not reach WebEngine; "
                f"loaded={renderer._loaded}, channel_ready={renderer._channel_ready}, "
                f"progress={renderer.progress}, error={renderer.errorMessage!r}"
            )

        requested: list[tuple[str, str]] = []
        popups: list[tuple[QObject, str]] = []
        renderer.itemRequested.connect(lambda uid, prefix: requested.append((uid, prefix)))
        renderer.popupCreated.connect(lambda popup, title: popups.append((popup, title)))
        getattr(window, "clickInternalLink")()
        qtbot.waitUntil(lambda: requested == [("REQ-A-002", "REQ-A")], timeout=10000)
        assert not popups
        assert cast(dict[str, Any], backend.selectedItem)["uid"] == "REQ-A-001"
        opened: list[str] = []

        def record_url(values: list[str], url: QUrl) -> bool:
            values.append(url.toString())
            return True

        monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: record_url(opened, url))
        getattr(window, "clickExternalLink")()
        qtbot.waitUntil(lambda: opened == ["https://example.test/"], timeout=10000)

        renderer.loadFailed("deliberate load error")
        assert "deliberate load error" in str(renderer.errorMessage)
        label = window.findChild(QObject, "renderErrorLabel")
        assert label is not None and label.property("visible")
        assert "deliberate load error" in label.property("text")

        from doorstop_edit.item_render.render_worker import ItemRenderer

        def fail_render(*_args: Any) -> None:
            raise ValueError("deliberate Markdown failure")

        monkeypatch.setattr(ItemRenderer, "_prepare", staticmethod(fail_render))
        renderer.refresh()
        qtbot.waitUntil(lambda: "deliberate Markdown failure" in str(renderer.errorMessage), timeout=10000)
        assert label.property("visible")
        assert "deliberate Markdown failure" in label.property("text")
        assert not qml_warnings, qml_warnings
    finally:
        renderer.shutdown()
        backend.shutdown()
        if window is not None:
            getattr(window, "close")()
            window.deleteLater()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()

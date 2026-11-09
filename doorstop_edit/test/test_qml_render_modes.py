"""RenderPreview integration: real Qt Quick, WebEngine, WebChannel and RenderWorker."""

import os
import re
import time
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from doorstop_edit.item_render import fragmented_markdown
from doorstop_edit.item_render.render_worker import ItemRenderer
from doorstop_edit.qml_backend import QmlBackend
from doorstop_edit.qml_render_bridge import QmlRenderBridge
from tools.gen_sample_tree import generate_tree

# Must happen before the QApplication fixture is constructed.
QtWebEngineQuick.initialize()


@pytest.fixture
def preview_host(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> Any:
    """Make the production component with a JS probe, then stop the actual worker."""
    instances: list[tuple[QmlBackend, QmlRenderBridge, QQmlApplicationEngine, QQmlComponent, QQuickWindow]] = []

    def create(
        num_docs: int = 1, count: int = 2, preserve_plantuml: bool = False
    ) -> tuple[QmlBackend, QmlRenderBridge, QQuickWindow]:
        generate_tree(tmp_path, num_docs=num_docs, num_req=count)
        # Avoid network-bound PlantUML diagrams: this suite exercises page/worker
        # lifecycle, not the external renderer.
        if not preserve_plantuml:
            for path in tmp_path.glob("REQ-*/*.yml"):
                path.write_text(re.sub(r"  ```plantuml.*?  ```", "  Plain diagram", path.read_text(), flags=re.S))
        else:
            target = tmp_path / "REQ-A" / "REQ-A-010.yml"
            target.write_text(target.read_text().replace("MakeFood()", "QML_RENDER_REGRESSION_2026"))
        backend = QmlBackend(root=tmp_path)
        backend.selectDocument("REQ-A")
        backend.selectItem("REQ-A-001")
        renderer = QmlRenderBridge(backend)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("previewRenderer", renderer)
        qml = b"""import QtQuick 2.15
import QtQuick.Controls 2.15
import "../qml" as App
ApplicationWindow {
    visible: true; width: 680; height: 460
    property var probe: null
    function inspect(uid) {
        preview.webView.runJavaScript(
            "(function(){var e=document.getElementById('" + uid + "');"
            + "return e ? {html:e.innerHTML,display:e.style.display,"
            + "selected:e.classList.contains('selected'),"
            + "count:document.querySelectorAll('.doorstop-item').length,"
            + "images:Array.from(e.querySelectorAll('img')).map(i=>[i.complete,i.naturalWidth])} : null})()",
            function(value) { probe = value })
    }
    App.RenderPreview { id: preview; objectName: "renderPreview"; anchors.fill: parent; renderBridge: previewRenderer }
}"""
        component = QQmlComponent(engine)
        component.setData(qml, QUrl.fromLocalFile(str(Path(__file__).resolve())))
        assert component.isReady(), component.errors()
        window = component.create()
        assert isinstance(window, QQuickWindow), component.errors()
        instances.append((backend, renderer, engine, component, window))
        qtbot.waitUntil(lambda: renderer._channel_ready and renderer._render_started, timeout=15000)
        return backend, renderer, window

    yield create
    for backend, renderer, engine, component, window in reversed(instances):
        renderer.shutdown()
        backend.shutdown()
        window.close()
        window.deleteLater()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def inspect(qtbot: QtBot, window: QQuickWindow, uid: str) -> dict[str, Any]:
    window.setProperty("probe", None)
    getattr(window, "inspect")(uid)
    qtbot.waitUntil(lambda: window.property("probe") is not None, timeout=10000)
    return cast(dict[str, Any], window.property("probe"))


def done(qtbot: QtBot, renderer: QmlRenderBridge) -> None:
    qtbot.waitUntil(lambda: not renderer.running and renderer.progress == 100, timeout=20000)


def test_large_document_progress_and_partial_save(preview_host: Any, qtbot: QtBot) -> None:
    backend, renderer, window = preview_host(count=70)
    progress = []
    renderer.stateChanged.connect(lambda: progress.append(renderer.progress))
    done(qtbot, renderer)
    row = inspect(qtbot, window, "REQ-A-003")
    assert row["count"] == 70
    assert "req-table" in row["html"]
    assert max(progress) == 100
    assert not renderer.errorMessage
    backend.selectItem("REQ-A-003")
    done(qtbot, renderer)
    page_changes = []
    updates = []
    renderer.pageChanged.connect(lambda: page_changes.append(True))
    renderer.htmlUpdateItem.connect(lambda uid, *_: updates.append(uid))
    backend.saveSelected("New saved preview header", "Updated preview body")
    done(qtbot, renderer)
    qtbot.waitUntil(lambda: "Updated preview body" in inspect(qtbot, window, "REQ-A-003")["html"], timeout=10000)
    assert "REQ-A-003" in updates
    assert not page_changes  # same document: update fragments rather than rebuilding the page
    assert "New saved preview header" in inspect(qtbot, window, "REQ-A-003")["html"]


@pytest.mark.skipif(
    os.environ.get("DOORSTOP_RUN_PLANTUML_NETWORK_TESTS") != "1",
    reason="requires the external PlantUML server; set DOORSTOP_RUN_PLANTUML_NETWORK_TESTS=1 to run",
)
def test_plantuml_block_is_rendered_in_webengine_preview(
    preview_host: Any, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fragmented_markdown, "PLANTUML_CACHE", tmp_path / "plantuml-cache")
    _, renderer, window = preview_host(count=10, preserve_plantuml=True)
    done(qtbot, renderer)

    rendered_html = inspect(qtbot, window, "REQ-A-010")["html"]
    assert "QML_RENDER_REGRESSION_2026" not in rendered_html
    assert "<img" in rendered_html
    qtbot.waitUntil(
        lambda: (
            bool(inspect(qtbot, window, "REQ-A-010")["images"])
            and all(image[0] and image[1] > 0 for image in inspect(qtbot, window, "REQ-A-010")["images"])
        ),
        timeout=60000,
    )
    assert not renderer.errorMessage


def test_modes_selection_restore_and_reload_during_active_work(
    preview_host: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ItemRenderer._render_item

    def slow(*args: Any) -> Any:
        time.sleep(0.006)
        return original(*args)

    monkeypatch.setattr(ItemRenderer, "_render_item", staticmethod(slow))
    backend, renderer, window = preview_host(count=36)
    renderer.setViewMode("item")
    renderer.reload()  # replaces an active request, mode must survive replacement
    backend.selectItem("REQ-A-003")
    renderer.setViewMode("section")
    done(qtbot, renderer)
    assert renderer.viewMode == "section"
    qtbot.waitUntil(lambda: inspect(qtbot, window, "REQ-A-003")["selected"], timeout=10000)
    assert inspect(qtbot, window, "REQ-A-002")["display"] == "block"  # section parent
    assert inspect(qtbot, window, "REQ-A-004")["display"] == "block"  # sibling
    assert inspect(qtbot, window, "REQ-A-019")["display"] == "none"  # other section
    renderer.setViewMode("item")
    qtbot.waitUntil(lambda: inspect(qtbot, window, "REQ-A-004")["display"] == "none", timeout=10000)
    assert inspect(qtbot, window, "REQ-A-003")["display"] == "block"
    renderer.setViewMode("document")
    qtbot.waitUntil(lambda: inspect(qtbot, window, "REQ-A-019")["display"] == "block", timeout=10000)
    renderer.reload()
    done(qtbot, renderer)
    assert inspect(qtbot, window, "REQ-A-003")["selected"]
    assert renderer.viewMode == "document"


def test_replaced_document_discards_old_worker_output(
    preview_host: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ItemRenderer._render_item

    def slow(*args: Any) -> Any:
        time.sleep(0.009)
        return original(*args)

    monkeypatch.setattr(ItemRenderer, "_render_item", staticmethod(slow))
    backend, renderer, window = preview_host(num_docs=2, count=32)
    backend.selectDocument("REQ-B")
    backend.selectItem("REQ-B-002")
    updates = []
    renderer.htmlUpdateItem.connect(lambda uid, *_: updates.append(uid))
    done(qtbot, renderer)
    qtbot.waitUntil(lambda: inspect(qtbot, window, "REQ-B-002")["selected"], timeout=10000)
    assert inspect(qtbot, window, "REQ-B-002")["count"] == 32
    assert not any(uid.startswith("REQ-A-") for uid in updates)
    # Rapid selections within a page must also restore focus to the last item.
    for uid in ("REQ-B-001", "REQ-B-003", "REQ-B-002", "REQ-B-004"):
        backend.selectItem(uid)
    done(qtbot, renderer)
    qtbot.waitUntil(lambda: inspect(qtbot, window, "REQ-B-004")["selected"], timeout=10000)
    assert not inspect(qtbot, window, "REQ-B-002")["selected"]


def test_worker_failure_completes_and_reload_recovers(
    preview_host: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend, renderer, window = preview_host(count=2)
    done(qtbot, renderer)
    original = ItemRenderer._prepare

    def fail(*_args: Any) -> None:
        raise ValueError("Markdown unavailable")

    monkeypatch.setattr(ItemRenderer, "_prepare", staticmethod(fail))
    renderer.reload()
    qtbot.waitUntil(lambda: "Markdown unavailable" in renderer.errorMessage, timeout=10000)
    qtbot.waitUntil(lambda: not renderer.running, timeout=10000)
    assert renderer.progress < 100
    label = window.findChild(QObject, "renderErrorLabel")
    assert label is not None and label.property("visible")
    monkeypatch.setattr(ItemRenderer, "_prepare", staticmethod(original))
    renderer.reload()
    done(qtbot, renderer)
    assert not renderer.errorMessage
    assert not label.property("visible")
    assert "req-table" in inspect(qtbot, window, "REQ-A-001")["html"]

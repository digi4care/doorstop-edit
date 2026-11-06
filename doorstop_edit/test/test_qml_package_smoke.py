"""Installed-wheel smoke check for packaged QML engine/component availability."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Avoid requiring a display server while still creating real Qt Quick objects.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWebEngineQuick import QtWebEngineQuick

from doorstop_edit.qml_backend import QmlBackend
from doorstop_edit.qml_render_bridge import QmlRenderBridge


def main() -> None:
    import doorstop_edit

    package = Path(doorstop_edit.__file__).resolve().parent
    if "site-packages" not in str(package) and "site-packages" not in str(package).replace("\\", "/"):
        raise AssertionError(f"Expected installed wheel, imported {package}")
    qml_file = package / "qml" / "Main.qml"
    if not qml_file.is_file():
        raise AssertionError(f"Packaged QML entry point is missing: {qml_file}")

    QtWebEngineQuick.initialize()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = QmlBackend(root=None)
    renderer = QmlRenderBridge(backend, engine)
    failures: list[str] = []
    engine.warnings.connect(lambda warnings: failures.extend(w.toString() for w in warnings))
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("previewRenderer", renderer)
    try:
        engine.load(QUrl.fromLocalFile(str(qml_file)))
        app.processEvents()
        root_objects = engine.rootObjects()
        if not root_objects:
            raise AssertionError(f"QQmlApplicationEngine failed to load {qml_file}")
        if root_objects[0].findChild(QObject, "renderWebView") is None:
            raise AssertionError("QML tree does not contain renderWebView")
        print(
            "Installed-wheel probe verified Main.qml, QtWebEngineQuick initialization, "
            "QmlRenderBridge context wiring, and renderWebView construction; "
            "it did not launch project rendering. Cross-platform runtime validation remains pending."
        )
    finally:
        renderer.shutdown()
        # Destroy QML objects and their bindings while renderer and backend remain alive.
        for root_object in engine.rootObjects():
            getattr(root_object, "close")()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        backend.shutdown()
        app.processEvents()
        del renderer, backend, engine

    if failures:
        raise AssertionError("QML runtime reported warnings/errors:\n" + "\n".join(failures))
    del app


if __name__ == "__main__":
    main()

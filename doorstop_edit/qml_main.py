import logging
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication

from doorstop_edit.main import create_parser
from doorstop_edit.qml_backend import QmlBackend
from doorstop_edit.qml_render_bridge import QmlRenderBridge
from doorstop_edit.utils.version_summary import create_version_summary

# Must precede QApplication/QGuiApplication construction for Qt Quick WebEngine.
QtWebEngineQuick.initialize()


def main() -> int:
    args = create_parser().parse_args(sys.argv[1:])
    if args.version:
        print(create_version_summary())
        return 0
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s [%(name)s] %(message)s")
    logging.getLogger("gui").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    root = Path(args.directory) if args.directory else None
    if root is not None and not root.is_dir():
        logging.getLogger("gui").error('Invalid argument: "%s" is not a directory.', root)
        return 0
    app = QApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    backend = QmlBackend(parent=engine, root=root)
    renderer = QmlRenderBridge(backend, engine)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("previewRenderer", renderer)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        renderer.shutdown()
        backend.shutdown()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return 1
    app.aboutToQuit.connect(renderer.shutdown)
    app.aboutToQuit.connect(backend.shutdown)
    exit_code = app.exec()
    # Dispose the QML bindings before their Python context object is destroyed.
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

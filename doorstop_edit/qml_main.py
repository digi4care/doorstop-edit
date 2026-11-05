import logging
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from doorstop_edit.main import create_parser
from doorstop_edit.qml_backend import QmlBackend
from doorstop_edit.utils.version_summary import create_version_summary


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
    backend = QmlBackend(root=root)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        backend.shutdown()
        return 1
    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

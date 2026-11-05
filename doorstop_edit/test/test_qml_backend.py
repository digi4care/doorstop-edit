from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, Qt, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from doorstop_edit import qml_main
from doorstop_edit.main import create_parser
from doorstop_edit.qml_backend import QmlBackend
from tools.gen_sample_tree import generate_tree


def dispose_qml(engine: QQmlApplicationEngine, backend: QmlBackend, qapp: QApplication) -> None:
    for root in engine.rootObjects():
        cast(QQuickWindow, root).close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    backend.shutdown()


def test_cli_parser_shared_semantics() -> None:
    args = create_parser().parse_args(["--verbose", "/tmp"])
    assert args.verbose and args.directory == "/tmp"
    assert create_parser().parse_args(["--version"]).version


def test_qml_engine_loads(qapp: QApplication) -> None:
    backend = cast(Any, QmlBackend())
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    dispose_qml(engine, backend, qapp)


def test_invalid_root_is_reported(qapp: QApplication, tmp_path: Path) -> None:
    backend = cast(Any, QmlBackend())
    backend.openProject(str(tmp_path / "missing"))
    assert "not a directory" in backend.errorMessage
    backend.shutdown()


def test_selection_save_notifications_and_shutdown(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    assert backend._data.file_watcher._started
    tree_changes = []
    saved = []
    backend.documentsChanged.connect(lambda: tree_changes.append(True))
    backend._data.item_saved.connect(lambda: saved.append(True))
    document = backend.documents[0]["prefix"]
    backend.selectDocument(document)
    assert set(backend.documents[0]) == {"prefix", "path", "parent", "count"}
    uid = backend.items[0]["uid"]
    assert set(backend.items[0]) == {"uid", "level", "header", "active", "normative"}
    backend.selectItem(uid)
    assert backend.selectedItem["uid"] == uid
    assert set(backend.selectedItem) == {"uid", "level", "header", "text"}
    backend.saveSelected("Changed header", "Changed text")
    assert saved and backend.selectedItem["header"] == "Changed header"
    assert tree_changes
    backend.shutdown()


def test_picker_calls_open_project(qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    backend = cast(Any, QmlBackend())
    selected = []
    monkeypatch.setattr(
        "doorstop_edit.qml_backend.QtWidgets.QFileDialog.getExistingDirectory",
        lambda *args: str(tmp_path),
    )
    monkeypatch.setattr(backend, "openProject", lambda path: selected.append(path))
    backend.openProjectPicker()
    assert selected == [str(tmp_path)]
    backend.shutdown()


def test_root_persistence_only_after_success(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend())

    class Settings:
        last_open_folder = ""

    backend._settings = Settings()
    backend.openProject(str(tmp_path / "missing"))
    assert backend._settings.last_open_folder == ""
    backend.openProject(str(tmp_path))
    assert backend._settings.last_open_folder == str(tmp_path)
    assert backend._data.file_watcher._started
    backend.shutdown()
    assert not backend._data.file_watcher._started


def test_successful_root_switch_clears_selection(qapp: QApplication, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    generate_tree(first, num_docs=1, num_req=1)
    generate_tree(second, num_docs=1, num_req=1)
    new_dir = second / "REQ-A"
    (new_dir / ".doorstop.yml").write_text((new_dir / ".doorstop.yml").read_text().replace("REQ-A", "REQ-Z"))
    new_dir.rename(second / "REQ-Z")
    new_dir = second / "REQ-Z"
    (new_dir / "REQ-A-001.yml").rename(new_dir / "REQ-Z-001.yml")
    backend = cast(Any, QmlBackend(root=first))
    backend.selectDocument("REQ-A")
    old_uid = backend.items[0]["uid"]
    backend.selectItem(old_uid)
    backend.openProject(str(second))
    assert backend.projectRoot == str(second)
    assert backend.documents[0]["prefix"] == "REQ-Z"
    assert backend.items == []
    assert backend.selectedItem == {"uid": "", "level": "", "header": "", "text": ""}
    assert old_uid != "REQ-Z-001"
    backend.shutdown()


def test_failed_root_switch_keeps_old_tree_selection_and_watcher(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    first = tmp_path / "valid"
    invalid = tmp_path / "invalid"
    first.mkdir()
    invalid.mkdir()
    (invalid / ".doorstop.yml").write_text("settings: [invalid")
    generate_tree(first, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=first))
    backend.selectDocument("REQ-A")
    uid = backend.items[0]["uid"]
    backend.selectItem(uid)
    original_header = backend.selectedItem["header"]
    backend.openProject(str(invalid))
    assert backend.projectRoot == str(first)
    assert backend.selectedItem["uid"] == uid
    assert backend.selectedItem["header"] == original_header
    assert backend._data.file_watcher._started
    assert backend._data.file_watcher.scheduled_docs
    item_path = first / "REQ-A" / "REQ-A-001.yml"
    with qtbot.waitSignal(backend.itemsChanged, timeout=4000):
        item_path.write_text(item_path.read_text() + "\n# external change\n")
    backend.shutdown()


def test_qml_editor_preserves_draft_after_external_update(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    document = backend.documents[0]["prefix"]
    backend.selectDocument(document)
    uid = backend.items[0]["uid"]
    backend.selectItem(uid)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    header = window.findChild(QObject, "headerField")
    conflict = window.findChild(QObject, "conflictMessage")
    assert header is not None and conflict is not None

    header.setProperty("text", "Local draft")
    item = backend._data.find_item(uid, document)
    assert item is not None
    item.header = "External update"
    item.text = "External body"
    item.save()

    qtbot.waitUntil(lambda: bool(conflict.property("visible")), timeout=5000)
    assert header.property("text") == "Local draft"
    assert backend.selectedItem["header"] == "External update"

    assert QMetaObject.invokeMethod(window, "saveCurrent")
    assert not conflict.property("visible")
    assert not window.property("isDirty")
    assert backend.selectedItem["header"] == "Local draft"
    dispose_qml(engine, backend, qapp)


def test_qml_project_open_select_and_save_interaction(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend())
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()
    qapp.processEvents()

    def quick_item(name: str) -> QQuickItem:
        item = cast(QQuickItem, window.findChild(QQuickItem, name))
        assert item is not None, f"QML item {name!r} was not created"
        return item

    project_path = quick_item("projectPath")
    project_path.setProperty("text", str(tmp_path))
    open_button = quick_item("openPathButton")
    click_point = open_button.mapToScene(open_button.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=click_point)
    qapp.processEvents()
    assert backend.projectRoot == str(tmp_path)

    document_list = quick_item("documentList")
    assert document_list.property("count") == 1
    document_list.setProperty("currentIndex", 0)
    qapp.processEvents()
    document_delegate = document_list.property("currentItem")
    assert document_delegate is not None
    assert QMetaObject.invokeMethod(document_delegate, "activate")
    qapp.processEvents()
    assert backend._selected_document == "REQ-A"

    item_list = quick_item("itemList")
    assert item_list.property("count") == 1
    item_list.setProperty("currentIndex", 0)
    qapp.processEvents()
    item_delegate = item_list.property("currentItem")
    assert item_delegate is not None
    assert QMetaObject.invokeMethod(item_delegate, "activate")
    qapp.processEvents()
    uid = backend.selectedItem["uid"]
    assert uid == "REQ-A-001"

    header = quick_item("headerField")
    body = quick_item("bodyField")
    header.setProperty("text", "Saved through QML")
    body.setProperty("text", "QML editor interaction")
    assert QMetaObject.invokeMethod(window, "saveCurrent")
    qapp.processEvents()
    assert backend.selectedItem["header"] == "Saved through QML"
    assert backend.selectedItem["text"] == "QML editor interaction"

    backend.openProject(str(tmp_path / "missing"))
    assert "not a directory" in backend.errorMessage
    assert backend.projectRoot == str(tmp_path)

    dispose_qml(engine, backend, qapp)


def test_qml_main_normal_shutdown_disposes_engine_before_backend(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    monkeypatch.setattr(qml_main, "QApplication", lambda _argv: qapp)
    monkeypatch.setattr("sys.argv", ["doorstop-edit-qml", str(tmp_path)])
    messages: list[str] = []
    previous_handler = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    shutdown_states: list[bool] = []
    original_shutdown = QmlBackend.shutdown

    def record_shutdown(backend: QmlBackend) -> None:
        original_shutdown(backend)
        shutdown_states.append(not backend._data.file_watcher._started)

    monkeypatch.setattr(QmlBackend, "shutdown", record_shutdown)

    def close_qml_window() -> None:
        for window in QGuiApplication.topLevelWindows():
            window.close()

    QTimer.singleShot(100, close_qml_window)
    try:
        assert qml_main.main() == 0
    finally:
        qInstallMessageHandler(previous_handler)

    assert shutdown_states == [True]
    assert not any("Cannot read property" in message for message in messages)

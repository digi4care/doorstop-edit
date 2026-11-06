from pathlib import Path
from threading import Thread
from typing import Any, cast

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMetaObject,
    QObject,
    Qt,
    QThread,
    QTimer,
    QUrl,
    qInstallMessageHandler,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot
from watchdog.events import FileModifiedEvent

from doorstop_edit import qml_main
from doorstop_edit.doorstop_data import ValidationFinding
from doorstop_edit.main import create_parser
from doorstop_edit.qml_backend import QmlBackend, ValidationRunResult
from tools.gen_sample_tree import generate_tree


def validation_result(
    root: Path,
    revision: int,
    run_id: str,
    findings: tuple = (),
    state: str = "succeeded",
    error: str | None = None,
) -> ValidationRunResult:
    resolved = str(root.resolve())
    return ValidationRunResult(resolved, revision, run_id, findings, state, None, None, error, resolved)


class FakeValidationService:
    instances: list["FakeValidationService"] = []

    def __init__(self, parent: QObject | None = None) -> None:
        class ResultSignal:
            def connect(_self, callback: Any) -> None:
                self.callback = callback

        self.result = ResultSignal()
        self.callback: Any = None
        self.requests: list[tuple[Path, int]] = []
        self.shutdown_called = False
        self.__class__.instances.append(self)

    def request(self, root: Path, content_revision: int) -> None:
        self.requests.append((root.resolve(), content_revision))

    def shutdown(self) -> None:
        self.shutdown_called = True

    def emit_result(self, result: ValidationRunResult) -> bool:
        return bool(self.callback(result))


def dispose_qml(engine: QQmlApplicationEngine, backend: QmlBackend, qapp: QApplication) -> None:
    for root in engine.rootObjects():
        cast(QQuickWindow, root).close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    backend.shutdown()


def test_qml_validation_service_requests_and_state_gating(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    generate_tree(first, num_docs=1, num_req=1)
    generate_tree(second, num_docs=1, num_req=1)
    FakeValidationService.instances.clear()
    monkeypatch.setattr("doorstop_edit.qml_backend.ValidationService", FakeValidationService)
    backend = cast(Any, QmlBackend(root=first))
    service = FakeValidationService.instances[-1]
    assert len(service.requests) == 1
    assert service.requests[0][0] == first.resolve()
    publications: list[dict] = []
    backend.graphChanged.connect(lambda: publications.append(backend.appGraph))

    def emit(
        root: Path,
        revision: int,
        run_id: str,
        state: str,
        findings: tuple = (),
        error: str | None = None,
    ) -> bool:
        return service.emit_result(validation_result(root, revision, run_id, findings, state, error))

    rev = backend._data.content_revision
    assert emit(first, rev, "run-1", "running")
    assert backend.appGraph["validationRun"]["state"] == "running"
    finding = ValidationFinding("warning", "prior", "REQ-A-001")
    assert emit(first, rev, "run-1", "succeeded", (finding,))
    assert backend.appGraph["validationRun"]["projectId"] == f"project:{first.resolve()}"
    backend._data.create_document("SUB", parent="REQ-A")
    current = backend._data.content_revision
    assert service.requests[-1] == (first.resolve(), current)
    node = next(n for n in backend.appGraph["nodes"] if n["type"] == "ValidationFinding")
    assert node["state"] == "stale"
    assert emit(first, current, "run-2", "running")
    assert emit(first, current, "run-2", "failed", error="failed")
    assert backend.appGraph["validationRun"]["state"] == "failed"
    node = next(n for n in backend.appGraph["nodes"] if n["type"] == "ValidationFinding")
    assert node["state"] == "stale" and node["message"] == "prior"

    generation = backend.appGraph["graphGeneration"]
    assert not emit(second, current, "wrong-root", "succeeded")
    bad_project = ValidationRunResult(
        str(first.resolve()), current, "wrong-project", (), "succeeded", None, None, None, "wrong"
    )
    assert not service.emit_result(bad_project)
    assert not emit(first, current - 1, "old-revision", "succeeded")
    backend.openProject(str(second))
    switched_revision = backend._data.content_revision
    assert len(service.requests) == 3
    assert not emit(first, current, "old-root", "succeeded")
    assert backend.appGraph["validationRun"]["state"] == "notRun"
    assert service.requests[-1] == (second.resolve(), switched_revision)
    assert backend.appGraph["graphGeneration"] > generation
    backend.shutdown()
    assert service.shutdown_called


def test_items_preserves_valid_rows_when_item_property_access_fails(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    backend.selectDocument("REQ-A")
    valid = backend._data.find_item("REQ-A-001", "REQ-A")
    assert valid is not None

    class MalformedItem:
        @property
        def uid(self) -> str:
            raise RuntimeError("malformed item")

    backend._data.iter_items = lambda _doc: iter((valid, MalformedItem()))
    rows = backend.items
    assert rows[0]["uid"] == "REQ-A-001"
    assert rows[1]["header"] == "Unable to load item: malformed item"
    assert rows[1]["active"] is False
    backend.shutdown()


def test_qml_initial_open_publishes_and_requests_once(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    FakeValidationService.instances.clear()
    monkeypatch.setattr("doorstop_edit.qml_backend.ValidationService", FakeValidationService)
    backend = cast(Any, QmlBackend(root=tmp_path))
    assert len(FakeValidationService.instances[-1].requests) == 1
    assert backend.appGraph["graphGeneration"] == 1
    backend.shutdown()


def test_request_validation_slot_uses_current_root_and_revision(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    FakeValidationService.instances.clear()
    monkeypatch.setattr("doorstop_edit.qml_backend.ValidationService", FakeValidationService)
    backend = cast(Any, QmlBackend(root=tmp_path))
    service = FakeValidationService.instances[-1]
    service.requests.clear()
    backend.requestValidation()
    assert service.requests == [(tmp_path.resolve(), backend._data.content_revision)]
    backend.shutdown()


def test_save_validation_request_only_after_success(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    FakeValidationService.instances.clear()
    monkeypatch.setattr("doorstop_edit.qml_backend.ValidationService", FakeValidationService)
    backend = cast(Any, QmlBackend(root=tmp_path))
    service = FakeValidationService.instances[-1]
    service.requests.clear()
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    backend.saveSelected("Updated", "Updated body")
    assert service.requests == [(tmp_path.resolve(), backend._data.content_revision)]

    service.requests.clear()
    saved: list[bool] = []
    errors: list[str] = []
    backend._data.item_saved.connect(lambda: saved.append(True))
    backend.errorMessageChanged.connect(lambda: errors.append(backend.errorMessage))
    backend._data.save_item = lambda _item: (_ for _ in ()).throw(OSError("save failed"))
    backend.saveSelected("Failed", "Failed body")
    assert service.requests == []
    assert saved == []
    assert errors and errors[-1] == "save failed"
    backend.shutdown()


def test_initial_running_validation_is_included_in_first_graph_snapshot(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    class SynchronousRunningService(FakeValidationService):
        def request(self, root: Path, content_revision: int) -> None:
            super().request(root, content_revision)
            resolved = str(root.resolve())
            self.callback(
                ValidationRunResult(
                    resolved, content_revision, "initial-run", (), "running", None, None, None, resolved
                )
            )

    generate_tree(tmp_path, num_docs=1, num_req=1)
    SynchronousRunningService.instances.clear()
    monkeypatch.setattr("doorstop_edit.qml_backend.ValidationService", SynchronousRunningService)
    backend = cast(Any, QmlBackend(root=tmp_path))
    assert backend.appGraph["graphGeneration"] == 1
    assert backend.appGraph["validationRun"]["state"] == "running"
    backend.shutdown()


def test_validator_spawn_failure_is_visible_and_cleans_up(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)

    def fail_to_start(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("validator launch failed")

    monkeypatch.setattr("doorstop_edit.validation_service.ValidationService._launch_owner", fail_to_start)
    backend = cast(Any, QmlBackend(root=tmp_path))
    run = backend.appGraph["validationRun"]
    assert run["state"] == "failed"
    assert "validator launch failed" in run["error"]
    assert backend._validation_service._active is None
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


def test_qml_validation_controls_request_and_exclusive_panels(
    qapp: QApplication, qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    FakeValidationService.instances.clear()
    monkeypatch.setattr("doorstop_edit.qml_backend.ValidationService", FakeValidationService)
    backend = cast(Any, QmlBackend(root=tmp_path))
    service = FakeValidationService.instances[-1]
    service.requests.clear()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()
    qapp.processEvents()

    def item(name: str) -> QQuickItem:
        found = window.findChild(QQuickItem, name)
        assert found is not None, f"QML item {name!r} was not created"
        return found

    validate = item("validateProjectButton")
    assert validate.property("enabled")
    assert QMetaObject.invokeMethod(validate, "clicked")
    assert service.requests == [(tmp_path.resolve(), backend._data.content_revision)]

    summary = item("validationSummaryButton")
    assert QMetaObject.invokeMethod(summary, "clicked")
    results = window.findChild(QObject, "validationDrawer")
    assert results is not None
    qtbot.waitUntil(lambda: bool(results.property("opened")))
    validation_list = item("validationResultsList")
    validation_list.forceActiveFocus()
    window.requestActivate()
    qapp.processEvents()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not results.property("opened"))
    qtbot.waitUntil(lambda: window.activeFocusItem() == summary)
    assert QMetaObject.invokeMethod(summary, "clicked")
    qtbot.waitUntil(lambda: bool(results.property("opened")))
    assert QMetaObject.invokeMethod(item("graphToggleButton"), "clicked")
    qtbot.waitUntil(lambda: bool(item("graphExplorer").property("active")))
    assert not results.property("opened")
    assert QMetaObject.invokeMethod(item("graphToggleButton"), "clicked")
    qtbot.waitUntil(lambda: not item("graphExplorer").property("active"))
    dispose_qml(engine, backend, qapp)


def test_qml_validation_finding_opens_associated_item(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    FakeValidationService.instances.clear()
    backend = cast(Any, QmlBackend(root=tmp_path))
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    revision = backend._data.content_revision
    assert backend.acceptValidationRun(
        validation_result(
            tmp_path,
            revision,
            "finding-navigation",
            (
                ValidationFinding("error", "REQ-A-002 has a broken link", "REQ-A-002"),
                ValidationFinding("warning", "Project-level warning", None),
            ),
        )
    )
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()
    qapp.processEvents()

    def item(name: str) -> QQuickItem:
        found = window.findChild(QQuickItem, name)
        assert found is not None, f"QML item {name!r} was not created"
        return found

    summary = item("validationSummaryButton")
    assert "1 error" in summary.property("text")
    assert "1 warning" in summary.property("text")
    assert QMetaObject.invokeMethod(summary, "clicked")
    results = item("validationResultsList")
    qtbot.waitUntil(lambda: results.property("count") == 2)
    results.setProperty("currentIndex", 0)
    delegate = results.property("currentItem")
    assert delegate is not None
    assert QMetaObject.invokeMethod(delegate, "activate")
    qtbot.waitUntil(lambda: backend.selectedItem["uid"] == "REQ-A-002")
    results_panel = window.findChild(QObject, "validationDrawer")
    assert results_panel is not None
    qtbot.waitUntil(lambda: not results_panel.property("opened"))
    assert item("headerField").property("text") == backend.selectedItem["header"]

    assert QMetaObject.invokeMethod(summary, "clicked")
    qtbot.waitUntil(lambda: results_panel.property("opened"))
    results.setProperty("currentIndex", 1)
    project_finding = results.property("currentItem")
    assert project_finding is not None
    assert QMetaObject.invokeMethod(project_finding, "activate")
    assert backend.selectedItem["uid"] == "REQ-A-002"
    assert results_panel.property("opened"), "project finding should stay in the results panel"

    assert backend.acceptValidationRun(
        validation_result(tmp_path, revision, "validation-failed", state="failed", error="validator unavailable")
    )
    qapp.processEvents()
    assert "Validation failed" in item("validationSummaryButton").property("text")
    failure_labels = [
        child
        for child in window.findChildren(QQuickItem)
        if child.property("text") == "Validation error: validator unavailable"
    ]
    assert failure_labels and failure_labels[0].property("visible")
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


def test_qml_graph_explorer_search_activation_and_return(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = cast(Any, QmlBackend(root=tmp_path))
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()

    def item(name: str) -> QQuickItem:
        found = window.findChild(QQuickItem, name)
        assert found is not None, f"QML item {name!r} was not created"
        return found

    explorer = item("graphExplorer")
    assert not explorer.property("active")
    assert backend.selectedItem["uid"] == "REQ-A-001"
    assert QMetaObject.invokeMethod(item("graphToggleButton"), "clicked")
    qtbot.waitUntil(lambda: bool(explorer.property("active")))
    search = item("graphSearchField")
    qtbot.waitUntil(lambda: window.activeFocusItem() == search)
    search.setProperty("text", "REQ-A-002")
    results = item("graphResultsList")
    qtbot.waitUntil(lambda: results.property("count") == 1)
    results.setProperty("currentIndex", 0)
    delegate = results.property("currentItem")
    assert delegate is not None
    assert QMetaObject.invokeMethod(delegate, "activate")
    assert item("graphOpenInEditorButton").property("enabled")
    assert QMetaObject.invokeMethod(item("graphOpenInEditorButton"), "clicked")
    qtbot.waitUntil(lambda: backend.selectedItem["uid"] == "REQ-A-002")
    assert item("headerField").property("text") == backend.selectedItem["header"]
    assert QMetaObject.invokeMethod(item("graphCloseButton"), "clicked")
    qtbot.waitUntil(lambda: not explorer.property("active"))
    assert backend.selectedItem["uid"] == "REQ-A-002"
    dispose_qml(engine, backend, qapp)


def test_qml_graph_exact_uid_replaces_focused_finding(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = cast(Any, QmlBackend(root=tmp_path))
    assert backend.acceptValidationRun(
        validation_result(
            tmp_path,
            backend._data.content_revision,
            "finding-uid-search",
            (ValidationFinding("warning", "REQ-A-002 has a broken link", "REQ-A-002"),),
        )
    )
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()
    explorer = cast(QQuickItem, window.findChild(QQuickItem, "graphExplorer"))
    search = cast(QQuickItem, window.findChild(QQuickItem, "graphSearchField"))
    assert explorer is not None and search is not None
    toggle = window.findChild(QObject, "graphToggleButton")
    assert toggle is not None and QMetaObject.invokeMethod(toggle, "clicked")
    qtbot.waitUntil(lambda: bool(explorer.property("active")))

    search.setProperty("text", "broken link")
    qtbot.waitUntil(lambda: len(explorer.property("results").toVariant()) == 1)
    finding_id = explorer.property("results").toVariant()[0]["id"]
    assert explorer.property("focusId") == finding_id
    search.setProperty("text", "REQ-A-002")
    qtbot.waitUntil(lambda: explorer.property("focusId") == "item:REQ-A-002")
    assert [node["id"] for node in explorer.property("results").toVariant()] == ["item:REQ-A-002"]
    close_button = window.findChild(QObject, "graphCloseButton")
    assert close_button is not None and QMetaObject.invokeMethod(close_button, "clicked")
    qtbot.waitUntil(lambda: not explorer.property("active"))
    qtbot.waitUntil(lambda: window.activeFocusItem() == toggle)
    dispose_qml(engine, backend, qapp)


def test_qml_graph_snapshot_clears_removed_relation_not_project_focus(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtCore import Q_ARG

    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = cast(Any, QmlBackend(root=tmp_path))
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()
    toggle = window.findChild(QObject, "graphToggleButton")
    explorer = cast(QQuickItem, window.findChild(QQuickItem, "graphExplorer"))
    assert toggle is not None and explorer is not None
    assert QMetaObject.invokeMethod(toggle, "clicked")
    qtbot.waitUntil(lambda: explorer.property("focusId") == "item:REQ-A-001")
    document_entry = next(
        entry for entry in explorer.property("mapNodes").toVariant() if entry["node"]["id"] == "document:REQ-A"
    )
    assert QMetaObject.invokeMethod(
        explorer,
        "choose",
        Q_ARG("QVariant", document_entry["node"]),
        Q_ARG("QVariant", document_entry["relation"]),
        Q_ARG("QVariant", document_entry["path"]),
        Q_ARG("QVariant", document_entry["edge"]),
    )
    assert explorer.property("focusId") == "document:REQ-A"
    assert explorer.property("focusEdge") is not None
    assert explorer.property("focusRelation") == "Contains item"

    backend._data.delete_item("REQ-A-001")
    qtbot.waitUntil(lambda: explorer.property("focusEdge") is None)
    assert explorer.property("focusId") == "document:REQ-A"
    assert explorer.property("focusPath") == ""
    assert explorer.property("focusRelation") == ""
    dispose_qml(engine, backend, qapp)


def test_qml_graph_filters(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = cast(Any, QmlBackend(root=tmp_path))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()

    def item(name: str) -> QQuickItem:
        found = window.findChild(QQuickItem, name)
        assert found is not None, f"QML item {name!r} was not created"
        return found

    assert QMetaObject.invokeMethod(item("graphToggleButton"), "clicked")
    results = item("graphResultsList")
    qtbot.waitUntil(lambda: results.property("count") >= 2)
    filters = item("graphActiveFilter")
    filters.setProperty("currentIndex", 2)
    qtbot.waitUntil(lambda: results.property("count") == 0)
    filters.setProperty("currentIndex", 0)
    qtbot.waitUntil(lambda: results.property("count") >= 2)
    dispose_qml(engine, backend, qapp)


def test_qml_graph_results_keyboard_navigation_and_activation(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = cast(Any, QmlBackend(root=tmp_path))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()

    def item(name: str) -> QQuickItem:
        found = window.findChild(QQuickItem, name)
        assert found is not None, f"QML item {name!r} was not created"
        return found

    assert QMetaObject.invokeMethod(item("graphToggleButton"), "clicked")
    results = item("graphResultsList")
    qtbot.waitUntil(lambda: results.property("count") >= 3)
    item("graphSearchField").forceActiveFocus()
    qtbot.waitUntil(lambda: window.activeFocusItem() == item("graphSearchField"))
    for _ in range(20):
        if window.activeFocusItem() == results:
            break
        QTest.keyClick(window, Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: window.activeFocusItem() == results)
    results.setProperty("currentIndex", 0)

    QTest.keyClick(window, Qt.Key.Key_Down)
    qtbot.waitUntil(lambda: results.property("currentIndex") == 1)
    QTest.keyClick(window, Qt.Key.Key_Down)
    qtbot.waitUntil(lambda: results.property("currentIndex") == 2)
    delegate = results.property("currentItem")
    assert delegate is not None
    target = delegate.property("node")
    assert target["type"] == "Item"
    QTest.keyClick(window, Qt.Key.Key_Return)
    explorer = item("graphExplorer")
    qtbot.waitUntil(lambda: explorer.property("focusId") == target["id"])
    assert item("graphOpenInEditorButton").property("enabled")
    dispose_qml(engine, backend, qapp)


def test_qml_graph_navigation_confirms_dirty_draft(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=2)
    backend = cast(Any, QmlBackend(root=tmp_path))
    backend.selectDocument("REQ-A")
    backend.selectItem("REQ-A-001")
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects()
    window = cast(QQuickWindow, engine.rootObjects()[0])
    window.show()

    def item(name: str) -> QQuickItem:
        found = window.findChild(QQuickItem, name)
        assert found is not None, f"QML item {name!r} was not created"
        return found

    header, body = item("headerField"), item("bodyField")
    header.setProperty("text", "Draft header")
    body.setProperty("text", "Draft body")
    assert QMetaObject.invokeMethod(item("graphToggleButton"), "clicked")
    qtbot.waitUntil(lambda: bool(item("graphExplorer").property("active")))
    item("graphSearchField").setProperty("text", "REQ-A-002")
    results = item("graphResultsList")
    qtbot.waitUntil(lambda: results.property("count") == 1)
    results.setProperty("currentIndex", 0)
    assert QMetaObject.invokeMethod(results.property("currentItem"), "activate")
    assert QMetaObject.invokeMethod(item("graphOpenInEditorButton"), "clicked")
    dialog = next(
        (child for child in window.findChildren(QObject) if child.property("title") == "Discard unsaved changes?"),
        None,
    )
    assert dialog is not None
    qtbot.waitUntil(lambda: bool(dialog.property("visible")))
    assert QMetaObject.invokeMethod(dialog, "reject")
    qtbot.waitUntil(lambda: not dialog.property("visible"))
    assert backend.selectedItem["uid"] == "REQ-A-001"
    assert header.property("text") == "Draft header"
    assert body.property("text") == "Draft body"

    assert QMetaObject.invokeMethod(results.property("currentItem"), "activate")
    assert QMetaObject.invokeMethod(item("graphOpenInEditorButton"), "clicked")
    qtbot.waitUntil(lambda: bool(dialog.property("visible")))
    assert QMetaObject.invokeMethod(dialog, "accept")
    qtbot.waitUntil(lambda: backend.selectedItem["uid"] == "REQ-A-002")
    assert header.property("text") == backend.selectedItem["header"]
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


def test_graph_publishes_once_for_save_and_validation_is_revision_gated(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    assert backend.appGraph["contentRevision"] == backend._data.content_revision
    changes = []
    backend.graphChanged.connect(lambda: changes.append(True))
    backend.selectDocument("REQ-A")
    uid = backend.items[0]["uid"]
    backend.selectItem(uid)
    backend.saveSelected("Graph header", "Graph text")
    assert len(changes) == 1
    revision = backend._data.content_revision
    generation = backend.appGraph["graphGeneration"]
    assert not backend.acceptValidationRun(validation_result(tmp_path, revision - 1, "stale"))
    assert not backend.acceptValidationRun(validation_result(tmp_path / "other", revision, "wrong-root"))
    assert backend.appGraph["graphGeneration"] == generation
    assert backend.acceptValidationRun(validation_result(tmp_path, revision, "current"))
    assert backend.appGraph["graphGeneration"] == generation + 1
    assert backend.appGraph["contentRevision"] == revision
    backend.shutdown()


def test_restore_and_delete_publish_updated_graph_once(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    item = backend._data.find_item("REQ-A-001", "REQ-A")
    assert item is not None
    original = Path(item.path).read_text()
    item.header = "Temporary"
    backend._data.save_item(item)
    item = backend._data.find_item("REQ-A-001", "REQ-A")
    assert item is not None
    published = []
    backend.graphChanged.connect(lambda: published.append(True))
    backend._data.restore_item(item)
    assert len(published) == 1
    assert "Temporary" not in Path(item.path).read_text()
    assert Path(item.path).read_text() == original
    assert "item:REQ-A-001" in [n["id"] for n in backend.appGraph["nodes"]]
    published.clear()
    backend._data.delete_item("REQ-A-001")
    assert len(published) == 1
    assert "item:REQ-A-001" not in [n["id"] for n in backend.appGraph["nodes"]]
    backend.shutdown()


def test_external_edit_updates_graph_within_one_second(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    from time import monotonic

    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    path = tmp_path / "REQ-A" / "REQ-A-001.yml"
    previous = path.read_text()
    events = []
    backend.graphChanged.connect(lambda: events.append(monotonic()))
    started = monotonic()
    path.write_text(previous + "\n# external graph update\n")
    qtbot.waitUntil(lambda: bool(events), timeout=1000)
    assert events[0] - started <= 1.0
    assert backend.appGraph["contentRevision"] > 1
    backend.shutdown()


def test_watcher_callback_from_python_thread_is_marshaled_to_qt_thread(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    data = backend._data
    data.stop()
    path = tmp_path / "REQ-A" / "REQ-A-001.yml"
    item = data.find_item("REQ-A-001", "REQ-A")
    assert item is not None
    previous_revision = data.content_revision
    generation = data.file_watcher.generation
    callback_threads: list[QThread] = []
    backend.graphChanged.connect(lambda: callback_threads.append(QThread.currentThread()))
    data.contentChanged.connect(lambda *_args: callback_threads.append(QThread.currentThread()))
    try:
        item.header = "External watcher update"
        item.save()
        worker = Thread(target=data._on_filewatch_callback, args=(True, (str(path),), generation))
        worker.start()
        worker.join()

        qtbot.waitUntil(lambda: backend.appGraph["contentRevision"] > previous_revision)
        node = next(node for node in backend.appGraph["nodes"] if node["id"] == "item:REQ-A-001")
        assert node["header"] == "External watcher update"
        assert callback_threads
        assert all(thread == qapp.thread() for thread in callback_threads)
    finally:
        backend.shutdown()


def test_validation_becomes_stale_after_content_mutation(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    rev = backend._data.content_revision
    finding = ValidationFinding("warning", "old", "REQ-A-001")
    result = validation_result(tmp_path, rev, "run-1", (finding,))
    assert backend.acceptValidationRun(result)
    item = backend._data.find_item("REQ-A-001", "REQ-A")
    assert item is not None
    item.header = "Mutation"
    backend._data.save_item(item)
    graph = backend.appGraph
    assert graph["validationRun"]["runId"] == "run-1"
    assert graph["validationRun"]["inputContentRevision"] == rev
    assert graph["validationRun"]["state"] == "succeeded"
    graph_finding = next(node for node in graph["nodes"] if node["type"] == "ValidationFinding")
    assert graph_finding["state"] == "stale"
    backend.shutdown()


def test_document_create_and_remove_each_publish_one_graph_snapshot(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    changes = []
    backend.graphChanged.connect(lambda: changes.append(True))

    backend._data.create_document("SUB", parent="REQ-A")
    assert len(changes) == 1
    assert "document:SUB" in [node["id"] for node in backend.appGraph["nodes"]]

    changes.clear()
    backend._data.remove_document("SUB")
    assert len(changes) == 1
    assert "document:SUB" not in [node["id"] for node in backend.appGraph["nodes"]]
    backend.shutdown()


def test_old_watcher_generation_cannot_publish_after_root_switch(qapp: QApplication, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    generate_tree(first, num_docs=1, num_req=1)
    generate_tree(second, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=first))
    old_generation = backend._data.file_watcher.generation
    old_item_path = first / "REQ-A" / "REQ-A-001.yml"

    backend.openProject(str(second))
    current_revision = backend._data.content_revision
    current_generation = backend.appGraph["graphGeneration"]
    backend._data._process_filewatch_callback(True, (str(old_item_path),), old_generation)

    assert backend._data.content_revision == current_revision
    assert backend.appGraph["graphGeneration"] == current_generation
    assert backend.projectRoot == str(second)
    backend.shutdown()


def test_pending_watcher_echo_after_save_is_ignored(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    item = backend._data.find_item("REQ-A-001", "REQ-A")
    assert item is not None
    previous_generation = backend._data.file_watcher.generation
    item_path = Path(item.path)
    published = []
    backend.graphChanged.connect(lambda: published.append(True))

    item.header = "Local save"
    backend._data.save_item(item)
    current_revision = backend._data.content_revision
    current_generation = backend.appGraph["graphGeneration"]
    backend._data._process_filewatch_callback(True, (str(item_path),), previous_generation)

    assert len(published) == 1
    assert backend._data.content_revision == current_revision
    assert backend.appGraph["graphGeneration"] == current_generation
    backend.shutdown()


def test_queued_old_watch_event_does_not_change_revision_or_graph(qapp: QApplication, tmp_path: Path) -> None:
    generate_tree(tmp_path, num_docs=1, num_req=1)
    backend = cast(Any, QmlBackend(root=tmp_path))
    watcher = backend._data.file_watcher
    revision = backend._data.content_revision
    graph_generation = backend.appGraph["graphGeneration"]
    publications: list[bool] = []
    backend.graphChanged.connect(lambda: publications.append(True))
    old_observer = watcher.observer
    old_watch = next(iter(old_observer._watches))

    # Stop dispatch before queuing the watchdog's actual (event, ObservedWatch) tuple.
    old_observer.stop()
    old_observer.join(timeout=5)
    assert not old_observer.is_alive()
    old_observer.event_queue.put((FileModifiedEvent(str(tmp_path / "REQ-A" / "REQ-A-001.yml")), old_watch))
    watcher.pause()
    watcher.resume()
    QTest.qWait(int(watcher.DEBOUNCE_SECONDS * 2000))

    assert publications == []
    assert backend._data.content_revision == revision
    assert backend.appGraph["graphGeneration"] == graph_generation

    backend.shutdown()

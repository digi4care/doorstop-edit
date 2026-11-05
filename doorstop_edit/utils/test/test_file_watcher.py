from pathlib import Path
from threading import Event
from time import sleep
from types import SimpleNamespace

from watchdog.events import FileDeletedEvent, FileModifiedEvent

from doorstop_edit.utils.file_watcher import FileWatcher


def test_modified_file_emits_change_signal(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, str]] = []

    def on_change(changed: bool, name: str) -> None:
        calls.append((changed, name))
        received.set()

    watcher = FileWatcher(on_change)
    try:
        watcher.start()
        watcher.watch([SimpleNamespace(path=tmp_path)])
        item = tmp_path / "item.yml"
        item.write_text("initial")
        assert received.wait(1)
        received.clear()
        calls.clear()
        item.write_text("updated")
        assert received.wait(1)
        assert calls == [(True, "item.yml")]
    finally:
        watcher.stop()


def test_structural_event_dominates_modification_in_batch(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, str]] = []

    def on_change(changed: bool, name: str) -> None:
        calls.append((changed, name))
        received.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "old.yml")))
    watcher.on_deleted(FileDeletedEvent(str(tmp_path / "new.yml")))
    assert received.wait(1)
    assert calls == [(False, "")]
    watcher.stop()


def test_multiple_modified_files_are_all_delivered(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, str]] = []

    def on_change(changed: bool, name: str) -> None:
        calls.append((changed, name))
        if len(calls) == 2:
            received.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "one.yml")))
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "two.yml")))
    assert received.wait(1)
    assert set(calls) == {(True, "one.yml"), (True, "two.yml")}
    watcher.stop()


def test_stop_discards_pending_change(tmp_path: Path) -> None:
    calls: list[tuple[object, ...]] = []
    watcher = FileWatcher(lambda *change: calls.append(change))
    watcher.on_deleted(FileDeletedEvent(str(tmp_path / "item.yml")))
    watcher.stop()
    sleep(watcher.DEBOUNCE_SECONDS * 2)
    assert calls == []


def test_observer_can_restart_after_stop(tmp_path: Path) -> None:
    watcher = FileWatcher(lambda *_: None)
    watcher.start()
    watcher.stop()
    watcher.start()
    watcher.stop()


def test_watch_and_resume_skip_missing_root(tmp_path: Path) -> None:
    missing_root = tmp_path / "removed-document"
    watcher = FileWatcher(lambda *_: None)

    watcher.watch([SimpleNamespace(path=missing_root)])
    watcher.resume()

    assert watcher.scheduled_docs == [SimpleNamespace(path=missing_root)]
    watcher.start()
    watcher.stop()

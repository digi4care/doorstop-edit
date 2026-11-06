from pathlib import Path
from threading import Event
from time import sleep
from types import SimpleNamespace

from watchdog.events import FileDeletedEvent, FileModifiedEvent

from doorstop_edit.utils.file_watcher import FileWatcher


def test_modified_file_emits_change_signal(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, tuple[str, ...], int]] = []

    def on_change(changed: bool, paths: tuple[str, ...], generation: int) -> None:
        calls.append((changed, paths, generation))
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
        assert calls == [(True, (str(item.resolve()),), watcher.generation)]
    finally:
        watcher.stop()


def test_structural_event_dominates_modification_in_batch(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, tuple[str, ...], int]] = []

    def on_change(changed: bool, paths: tuple[str, ...], generation: int) -> None:
        calls.append((changed, paths, generation))
        received.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "old.yml")))
    watcher.on_deleted(FileDeletedEvent(str(tmp_path / "new.yml")))
    assert received.wait(1)
    assert calls == [(False, (str((tmp_path / "old.yml").resolve()), str((tmp_path / "new.yml").resolve())), 0)]
    watcher.stop()


def test_multiple_modified_files_are_all_delivered(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, tuple[str, ...], int]] = []

    def on_change(changed: bool, paths: tuple[str, ...], generation: int) -> None:
        calls.append((changed, paths, generation))
        received.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "one.yml")))
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "two.yml")))
    assert received.wait(1)
    assert calls == [(True, (str((tmp_path / "one.yml").resolve()), str((tmp_path / "two.yml").resolve())), 0)]
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


def test_pause_discards_queued_changes_and_advances_generation(tmp_path: Path) -> None:
    calls: list[tuple[bool, tuple[str, ...], int]] = []
    watcher = FileWatcher(lambda changed, paths, generation: calls.append((changed, paths, generation)))
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "item.yml")))
    previous_generation = watcher.generation
    watcher.pause()
    sleep(watcher.DEBOUNCE_SECONDS * 2)
    assert calls == []
    assert watcher.generation == previous_generation + 1
    watcher.stop()


def test_queued_event_from_old_watch_period_is_ignored(tmp_path: Path) -> None:
    calls: list[tuple[bool, tuple[str, ...], int]] = []
    watcher = FileWatcher(lambda changed, paths, generation: calls.append((changed, paths, generation)))
    watcher.start()
    watcher.watch([SimpleNamespace(path=tmp_path)])
    old_observer = watcher.observer
    old_watch = next(iter(old_observer._watches))

    # Stop dispatch first so this exact queued (event, watch) survives until pause.
    old_observer.stop()
    old_observer.join(timeout=5)
    assert not old_observer.is_alive()
    old_observer.event_queue.put((FileModifiedEvent(str(tmp_path / "item.yml")), old_watch))
    watcher.pause()
    watcher.resume()

    sleep(watcher.DEBOUNCE_SECONDS * 2)
    assert calls == []

    received = Event()

    def on_change(changed: bool, paths: tuple[str, ...], generation: int) -> None:
        calls.append((changed, paths, generation))
        received.set()

    watcher.on_dir_changed = on_change
    fresh_watch = next(iter(watcher.observer._watches))
    watcher.observer.event_queue.put((FileModifiedEvent(str(tmp_path / "fresh.yml")), fresh_watch))
    assert received.wait(1)
    assert calls == [(True, (str((tmp_path / "fresh.yml").resolve()),), watcher.generation)]
    watcher.stop()


def test_repeated_pause_preserves_started_state_for_watch_recovery(tmp_path: Path) -> None:
    watcher = FileWatcher(lambda *_: None)
    watcher.start()
    docs = [SimpleNamespace(path=tmp_path)]
    watcher.watch(docs)
    first_observer = watcher.observer

    watcher.pause()
    watcher.watch(docs)  # Failed tree rebuild recovery pauses again before rescheduling.

    assert watcher.observer is not first_observer
    assert watcher._started
    assert watcher.observer.is_alive()
    watcher.stop()

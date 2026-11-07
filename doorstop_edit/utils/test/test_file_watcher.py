from collections.abc import Callable
from pathlib import Path
from threading import Barrier, Event, Thread
from time import sleep
from types import SimpleNamespace

from pytest import MonkeyPatch
from watchdog.events import FileDeletedEvent, FileModifiedEvent
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

import doorstop_edit.utils.file_watcher as file_watcher_module
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


def test_callback_from_old_watch_period_is_ignored(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, tuple[str, ...], int]] = []

    def on_change(changed: bool, paths: tuple[str, ...], generation: int) -> None:
        calls.append((changed, paths, generation))
        received.set()

    watcher = FileWatcher(on_change)
    watcher.watch([SimpleNamespace(path=tmp_path)])
    old_handler = watcher._handler
    assert old_handler is not None
    old_generation = watcher.generation

    # Dispatch the old watch's callback after the generation changes. Avoid
    # relying on native observer queue timing, which differs by OS.
    watcher.pause()
    watcher.resume()
    assert watcher.generation == old_generation + 1
    old_handler.on_modified(FileModifiedEvent(str(tmp_path / "item.yml")))
    sleep(watcher.DEBOUNCE_SECONDS * 2)
    assert calls == []

    fresh_handler = watcher._handler
    assert fresh_handler is not None
    fresh_handler.on_modified(FileModifiedEvent(str(tmp_path / "fresh.yml")))
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


def test_observer_factory_selects_polling_only_on_windows(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(file_watcher_module, "os_name", "nt")
    assert isinstance(FileWatcher(lambda *_: None).observer, PollingObserver)
    monkeypatch.setattr(file_watcher_module, "os_name", "posix")
    assert type(FileWatcher(lambda *_: None).observer) is Observer


def test_stop_waits_for_in_flight_delivery() -> None:
    entered = Event()
    release = Event()
    returned = Event()

    def callback(*_args: object) -> None:
        entered.set()
        release.wait(2)

    watcher = FileWatcher(callback)
    watcher._queue_change(True, "/tmp/item.yml")
    assert entered.wait(1)

    def stop_watcher() -> None:
        watcher.stop()
        returned.set()

    stopper = Thread(target=stop_watcher)
    stopper.start()
    sleep(0.05)
    assert not returned.is_set()
    release.set()
    stopper.join(1)
    assert returned.is_set()


def test_stale_timer_callback_does_not_flush_newer_batch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback, self.args = callback, args
            timers.append(self)

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    calls: list[tuple[bool, tuple[str, ...], int]] = []
    watcher = FileWatcher(lambda *change: calls.append(change))
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "one.yml")))
    stale = timers[-1]
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "two.yml")))
    current = timers[-1]
    stale.callback(*stale.args)
    assert calls == []
    current.callback(*current.args)
    assert len(calls) == 1 and set(calls[0][1]) == {
        str((tmp_path / "one.yml").resolve()),
        str((tmp_path / "two.yml").resolve()),
    }
    watcher.stop()


def test_observer_restores_watches_after_restart(tmp_path: Path) -> None:
    received = Event()
    watcher = FileWatcher(lambda *_: received.set())
    watcher.start()
    watcher.watch([SimpleNamespace(path=tmp_path)])
    watcher.stop()
    watcher.start()
    try:
        (tmp_path / "restarted.yml").write_text("new")
        assert received.wait(2)
    finally:
        watcher.stop()


def test_watch_schedules_once_before_start_and_while_running(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    watcher = FileWatcher(lambda *_: None)
    root = tmp_path / "root"
    root.mkdir()
    scheduled: list[str] = []
    monkeypatch.setattr(
        BaseObserver, "schedule", lambda _observer, _handler, path, recursive=False: scheduled.append(path)
    )
    watcher.watch([SimpleNamespace(path=root)])
    assert len(scheduled) == 1
    watcher.start()
    assert len(scheduled) == 1
    watcher.watch([SimpleNamespace(path=root)])
    assert len(scheduled) == 1
    watcher.stop()


def test_reentrant_stop_from_callback_completes(tmp_path: Path) -> None:
    stopped = Event()
    watcher: FileWatcher

    def callback(*_args: object) -> None:
        watcher.stop()
        stopped.set()

    watcher = FileWatcher(callback)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "item.yml")))
    assert stopped.wait(1)


def test_reentrant_stop_waits_for_other_delivery(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback, self.args = callback, args
            timers.append(self)

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    entered, release, stopped = Event(), Event(), Event()

    def callback(_changed: bool, paths: tuple[str, ...], _generation: int) -> None:
        if "other.yml" in paths[0]:
            entered.set()
            release.wait(2)
        else:
            watcher.stop()
            stopped.set()

    watcher = FileWatcher(callback)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "other.yml")))
    first = timers[-1]
    a = Thread(target=first.callback, args=first.args)
    a.start()
    assert entered.wait(1)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "reentrant.yml")))
    second = timers[-1]
    b = Thread(target=second.callback, args=second.args)
    b.start()
    assert not stopped.wait(0.05)
    release.set()
    assert stopped.wait(1)
    a.join(1)
    b.join(1)
    assert not a.is_alive() and not b.is_alive()


def test_concurrent_reentrant_stops_do_not_deadlock(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback, self.args = callback, args
            timers.append(self)

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    ready = Event()
    barrier = Barrier(2)
    watcher: FileWatcher
    completed = 0

    def callback(_changed: bool, _paths: tuple[str, ...], _generation: int) -> None:
        nonlocal completed
        barrier.wait(timeout=1)
        watcher.stop()
        completed += 1
        if completed == 2:
            ready.set()

    watcher = FileWatcher(callback)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "first.yml")))
    first = timers[-1]
    a = Thread(target=first.callback, args=first.args, daemon=True)
    a.start()
    # The first callback is now in flight. A new event gets a fresh timer token
    # and may independently deliver while that callback is still active.
    while watcher._active_deliveries == 0:
        sleep(0.001)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "second.yml")))
    second = timers[-1]
    b = Thread(target=second.callback, args=second.args, daemon=True)
    b.start()
    assert ready.wait(2)
    a.join(1)
    b.join(1)
    assert not a.is_alive() and not b.is_alive()

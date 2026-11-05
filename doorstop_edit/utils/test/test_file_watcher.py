from collections.abc import Callable
from pathlib import Path
from threading import Barrier, Event, Thread
from time import sleep
from types import SimpleNamespace

from pytest import MonkeyPatch
from watchdog.events import FileDeletedEvent, FileModifiedEvent

import doorstop_edit.utils.file_watcher as file_watcher_module
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


def test_stale_timer_callback_does_not_flush_newer_batch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback = callback
            self.args = args

        def start(self) -> None:
            timers.append(self)

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    calls: list[tuple[bool, str]] = []
    watcher = FileWatcher(lambda *change: calls.append(change))

    watcher.on_modified(FileModifiedEvent(str(tmp_path / "first.yml")))
    stale_timer = timers[-1]
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "second.yml")))
    current_timer = timers[-1]

    stale_timer.callback(*stale_timer.args)
    assert calls == []

    current_timer.callback(*current_timer.args)
    assert calls == [(True, "first.yml"), (True, "second.yml")]
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


def test_observer_restores_watches_after_restart(tmp_path: Path) -> None:
    received = Event()
    calls: list[tuple[bool, str]] = []

    def on_change(changed: bool, name: str) -> None:
        calls.append((changed, name))
        received.set()

    watcher = FileWatcher(on_change)
    watcher.start()
    watcher.watch([SimpleNamespace(path=tmp_path)])
    watcher.stop()
    watcher.start()
    try:
        item = tmp_path / "after-restart.yml"
        item.write_text("initial")
        assert received.wait(2)
        received.clear()
        item.write_text("updated")
        assert received.wait(2)
        assert (True, "after-restart.yml") in calls
    finally:
        watcher.stop()


def test_stop_waits_for_in_flight_delivery(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback = callback
            self.args = args

        def start(self) -> None:
            timers.append(self)

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    callback_entered = Event()
    release_callback = Event()
    stop_started = Event()
    stop_finished = Event()

    def on_change(_changed: bool, _name: str) -> None:
        callback_entered.set()
        assert release_callback.wait(2)

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "blocked.yml")))
    timer = timers[-1]
    delivery = Thread(target=timer.callback, args=timer.args)
    delivery.start()
    assert callback_entered.wait(1)

    def stop_watcher() -> None:
        stop_started.set()
        watcher.stop()
        stop_finished.set()

    stopper = Thread(target=stop_watcher)
    stopper.start()
    assert stop_started.wait(1)
    assert not stop_finished.wait(0.05)
    release_callback.set()
    assert stop_finished.wait(1)
    delivery.join(timeout=1)
    stopper.join(timeout=1)
    assert not delivery.is_alive()
    assert not stopper.is_alive()


def test_watch_schedules_once_before_start_and_while_running(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    watcher = FileWatcher(lambda *_: None)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    scheduled: list[str] = []

    def schedule(_handler: object, path: str, recursive: bool = False) -> None:
        assert recursive
        scheduled.append(path)

    monkeypatch.setattr(watcher.observer, "schedule", schedule)
    monkeypatch.setattr(watcher.observer, "unschedule_all", lambda: None)
    watcher.watch([SimpleNamespace(path=first), SimpleNamespace(path=second)])
    assert scheduled == [str(first), str(second)]

    watcher.start()
    assert scheduled == [str(first), str(second)]
    third = tmp_path / "third"
    third.mkdir()
    watcher.watch([SimpleNamespace(path=third)])
    assert scheduled == [str(first), str(second), str(third)]
    watcher.stop()


def test_reentrant_stop_waits_for_other_delivery(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback = callback
            self.args = args

        def start(self) -> None:
            timers.append(self)

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    other_entered = Event()
    release_other = Event()
    reentrant_stop_returned = Event()

    def on_change(_changed: bool, name: str) -> None:
        if name == "other.yml":
            other_entered.set()
            assert release_other.wait(2)
        else:
            watcher.stop()
            reentrant_stop_returned.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "other.yml")))
    other_timer = timers[-1]
    other_delivery = Thread(target=other_timer.callback, args=other_timer.args)
    other_delivery.start()
    assert other_entered.wait(1)

    watcher.on_modified(FileModifiedEvent(str(tmp_path / "reentrant.yml")))
    reentrant_timer = timers[-1]
    reentrant_delivery = Thread(target=reentrant_timer.callback, args=reentrant_timer.args)
    reentrant_delivery.start()

    assert not reentrant_stop_returned.wait(0.05)
    release_other.set()
    assert reentrant_stop_returned.wait(1)
    other_delivery.join(timeout=1)
    reentrant_delivery.join(timeout=1)
    assert not other_delivery.is_alive()
    assert not reentrant_delivery.is_alive()


def test_concurrent_reentrant_stops_do_not_deadlock(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FakeTimer:
        def __init__(self, _delay: float, callback: Callable[..., None], args: tuple[int, ...] = ()) -> None:
            self.callback = callback
            self.args = args

        def start(self) -> None:
            timers.append(self)

        def cancel(self) -> None:
            pass

    timers: list[FakeTimer] = []
    monkeypatch.setattr(file_watcher_module, "Timer", FakeTimer)
    first_callback_entered = Event()
    callbacks_ready = Barrier(2)
    stopped = Event()
    completed_callbacks = 0

    def on_change(_changed: bool, _name: str) -> None:
        nonlocal completed_callbacks
        if _name == "first.yml":
            first_callback_entered.set()
        callbacks_ready.wait(timeout=1)
        watcher.stop()
        completed_callbacks += 1
        if completed_callbacks == 2:
            stopped.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "first.yml")))
    first_timer = timers[-1]
    first_delivery = Thread(target=first_timer.callback, args=first_timer.args, daemon=True)
    first_delivery.start()
    assert first_callback_entered.wait(1)

    watcher.on_modified(FileModifiedEvent(str(tmp_path / "second.yml")))
    second_timer = timers[-1]
    second_delivery = Thread(target=second_timer.callback, args=second_timer.args, daemon=True)
    second_delivery.start()

    assert stopped.wait(1)
    first_delivery.join(timeout=1)
    second_delivery.join(timeout=1)
    assert not first_delivery.is_alive()
    assert not second_delivery.is_alive()
    assert completed_callbacks == 2


def test_reentrant_stop_from_callback_completes(tmp_path: Path) -> None:
    stopped = Event()
    watcher: FileWatcher

    def on_change(_changed: bool, _name: str) -> None:
        watcher.stop()
        stopped.set()

    watcher = FileWatcher(on_change)
    watcher.on_modified(FileModifiedEvent(str(tmp_path / "item.yml")))
    assert stopped.wait(1)


def test_watch_and_resume_skip_missing_root(tmp_path: Path) -> None:
    missing_root = tmp_path / "removed-document"
    watcher = FileWatcher(lambda *_: None)

    watcher.watch([SimpleNamespace(path=missing_root)])
    watcher.resume()

    assert watcher.scheduled_docs == [SimpleNamespace(path=missing_root)]
    watcher.start()
    watcher.stop()

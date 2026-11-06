from os import fsdecode
from os import name as os_name
from pathlib import Path
from threading import Condition, Lock, Timer, get_ident
from typing import Callable, List

from doorstop import Document
from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver


class _GenerationHandler(FileSystemEventHandler):
    """Bind watchdog callbacks to the generation of one watch period."""

    def __init__(self, watcher: "FileWatcher", generation: int) -> None:
        super().__init__()
        self._watcher = watcher
        self._generation = generation

    def on_moved(self, event: FileSystemEvent) -> None:
        self._watcher._handle_event(False, event, self._generation)

    def on_created(self, event: FileSystemEvent) -> None:
        self._watcher._handle_event(False, event, self._generation)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._watcher._handle_event(False, event, self._generation)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher._handle_event(True, event, self._generation)


class FileWatcher(FileSystemEventHandler):
    DEBOUNCE_SECONDS = 0.1
    POLLING_INTERVAL_SECONDS = 0.1

    @classmethod
    def _new_observer(cls) -> BaseObserver:
        if os_name == "nt":
            return PollingObserver(timeout=cls.POLLING_INTERVAL_SECONDS)
        return Observer()

    def __init__(self, on_dir_changed: Callable[[bool, tuple[str, ...], int], None]) -> None:
        self.on_dir_changed = on_dir_changed
        self.observer = self._new_observer()
        self.scheduled_docs: List[Document] = []
        self._lock = Lock()
        self._delivery_finished = Condition(self._lock)
        self._active_deliveries = 0
        self._delivery_threads: set[int] = set()
        self._stop_coordinator: int | None = None
        self._timer: Timer | None = None
        self._timer_generation = 0
        self._pending_changes: dict[str, tuple[bool, int]] = {}
        self._stopped = False
        self._started = False
        self._scheduled = False
        self._generation = 0
        self._handler: _GenerationHandler | None = None
        self._resume_started = False

    def start(self) -> None:
        if self._started:
            return
        if self._stopped:
            self.observer = self._new_observer()
            self._stopped = False
        self.observer.start()
        self._started = True
        if not self._scheduled and self.scheduled_docs:
            self.resume()

    def stop(self) -> None:
        self._stopped = True
        self._resume_started = False
        with self._lock:
            self._generation += 1
            self._timer_generation += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_changes.clear()
            self._scheduled = False
            current_thread = get_ident()
            if current_thread in self._delivery_threads:
                if self._stop_coordinator is None:
                    self._stop_coordinator = current_thread
                    try:
                        while self._active_deliveries > 1:
                            self._delivery_finished.wait()
                    finally:
                        self._stop_coordinator = None
                        self._delivery_finished.notify_all()
                # Another delivery is already coordinating shutdown. Let this
                # callback return so it can finish and wake the coordinator.
                else:
                    pass
            else:
                while self._active_deliveries:
                    self._delivery_finished.wait()
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=5)
            if self.observer.is_alive():
                raise RuntimeError("File watcher observer did not stop within 5 seconds")
        self._started = False

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def pause(self) -> None:
        self._resume_started = self._started or self._resume_started
        with self._lock:
            self._generation += 1
            self._timer_generation += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_changes.clear()
            self._scheduled = False
        old_observer = self.observer
        if old_observer.is_alive():
            old_observer.stop()
            old_observer.join(timeout=5)
            if old_observer.is_alive():
                raise RuntimeError("File watcher observer did not stop within 5 seconds; refusing concurrent observer")
        self._started = False
        # Replacing the stopped observer discards its queued watchdog events.
        self.observer = self._new_observer()

    def resume(self) -> None:
        scheduled = False
        for doc in self.scheduled_docs:
            path = Path(doc.path)
            if path.is_dir():
                try:
                    with self._lock:
                        handler = _GenerationHandler(self, self._generation)
                        self._handler = handler
                    self.observer.schedule(handler, str(path), recursive=True)
                    scheduled = True
                except OSError:
                    # A document root may disappear between checking and scheduling.
                    continue
        self._scheduled = scheduled
        if self._resume_started and not self._stopped:
            self.observer.start()
            self._started = True
        self._resume_started = False

    def watch(self, docs: List[Document]) -> None:
        docs = list(docs)
        old_paths = tuple(str(Path(doc.path).resolve()) for doc in self.scheduled_docs)
        new_paths = tuple(str(Path(doc.path).resolve()) for doc in docs)
        if old_paths == new_paths and self._scheduled:
            return
        self.pause()
        self.scheduled_docs = docs
        self.resume()

    def _queue_change(self, changed: bool, path: str, generation: int | None = None) -> None:
        with self._lock:
            if self._stopped:
                return
            event_generation = self._generation if generation is None else generation
            if event_generation != self._generation:
                return
            # False means a structural change and dominates content reloads.
            old = self._pending_changes.get(path)
            self._pending_changes[path] = (changed if old is None else old[0] and changed, event_generation)
            if self._timer is not None:
                self._timer.cancel()
            self._timer_generation += 1
            timer_generation = self._timer_generation
            self._timer = Timer(self.DEBOUNCE_SECONDS, self._flush_change, args=(timer_generation,))
            self._timer.daemon = True
            self._timer.start()

    def _flush_change(self, timer_generation: int) -> None:
        with self._delivery_finished:
            if self._stopped or timer_generation != self._timer_generation:
                return
            changes = self._pending_changes
            self._pending_changes = {}
            self._timer = None
            generation = self._generation
            valid = tuple(
                path for path, (_changed, event_generation) in changes.items() if event_generation == generation
            )
            if not valid:
                return
            self._active_deliveries += 1
            delivery_thread = get_ident()
            self._delivery_threads.add(delivery_thread)
        try:
            structural = any(
                not changed for changed, event_generation in changes.values() if event_generation == generation
            )
            self.on_dir_changed(not structural, valid, generation)
        finally:
            with self._delivery_finished:
                self._active_deliveries -= 1
                self._delivery_threads.remove(delivery_thread)
                self._delivery_finished.notify_all()

    def _handle_event(self, changed: bool, event: FileSystemEvent, generation: int) -> None:
        self._queue_change(changed, str(Path(fsdecode(event.src_path)).resolve()), generation)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._handle_event(False, event, self.generation)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle_event(False, event, self.generation)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle_event(False, event, self.generation)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            # Dont care.
            return
        self._handle_event(True, event, self.generation)

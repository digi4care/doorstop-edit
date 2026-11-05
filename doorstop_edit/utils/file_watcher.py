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


class FileWatcher(FileSystemEventHandler):
    DEBOUNCE_SECONDS = 0.1
    POLLING_INTERVAL_SECONDS = 0.1

    @classmethod
    def _new_observer(cls) -> BaseObserver:
        if os_name == "nt":
            return PollingObserver(timeout=cls.POLLING_INTERVAL_SECONDS)
        return Observer()

    def __init__(self, on_dir_changed: Callable[[bool, str], None]) -> None:
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
        self._pending_changes: dict[str, bool] = {}
        self._stopped = False
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        restarting = self._stopped
        if restarting:
            self.observer = self._new_observer()
            self._stopped = False
        self.observer.start()
        self._started = True
        if restarting:
            self.resume()

    def stop(self) -> None:
        self._stopped = True
        with self._lock:
            self._timer_generation += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_changes.clear()
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
            else:
                while self._active_deliveries:
                    self._delivery_finished.wait()
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=5)
        self._started = False

    def pause(self) -> None:
        self.observer.unschedule_all()

    def resume(self) -> None:
        for doc in self.scheduled_docs:
            path = Path(doc.path)
            if path.is_dir():
                try:
                    self.observer.schedule(self, str(path), recursive=True)
                except OSError:
                    # A document root may disappear between checking and scheduling.
                    continue

    def watch(self, docs: List[Document]) -> None:
        if len(self.scheduled_docs) > 0:
            self.observer.unschedule_all()
        self.scheduled_docs = list(docs)
        self.resume()

    def _queue_change(self, changed: bool, name: str) -> None:
        with self._lock:
            if self._stopped:
                return
            # False means a structural change and dominates content reloads.
            self._pending_changes[name] = self._pending_changes.get(name, True) and changed
            self._timer_generation += 1
            generation = self._timer_generation
            if self._timer is not None:
                self._timer.cancel()
            self._timer = Timer(self.DEBOUNCE_SECONDS, self._flush_change, args=(generation,))
            self._timer.daemon = True
            self._timer.start()

    def _flush_change(self, generation: int) -> None:
        with self._lock:
            if generation != self._timer_generation:
                return
            changes = self._pending_changes
            self._pending_changes = {}
            self._timer = None
            if self._stopped or not changes:
                return
            self._active_deliveries += 1
            delivery_thread = get_ident()
            self._delivery_threads.add(delivery_thread)
        try:
            if not all(changes.values()):
                # Empty filename requests a full structural refresh without stale paths.
                self.on_dir_changed(False, "")
            else:
                for name in changes:
                    self.on_dir_changed(True, name)
        finally:
            with self._delivery_finished:
                self._active_deliveries -= 1
                self._delivery_threads.remove(delivery_thread)
                self._delivery_finished.notify_all()

    def on_moved(self, event: FileSystemEvent) -> None:
        self._queue_change(False, Path(fsdecode(event.src_path)).name)

    def on_created(self, event: FileSystemEvent) -> None:
        self._queue_change(False, Path(fsdecode(event.src_path)).name)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._queue_change(False, Path(fsdecode(event.src_path)).name)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            # Dont care.
            return

        self._queue_change(True, Path(fsdecode(event.src_path)).name)

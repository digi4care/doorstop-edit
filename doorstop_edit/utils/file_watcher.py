from os import fsdecode
from pathlib import Path
from threading import Lock, Timer
from typing import Callable, List

from doorstop import Document
from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer


class FileWatcher(FileSystemEventHandler):
    DEBOUNCE_SECONDS = 0.1

    def __init__(self, on_dir_changed: Callable[[bool, str], None]) -> None:
        self.on_dir_changed = on_dir_changed
        self.observer = Observer()
        self.scheduled_docs: List[Document] = []
        self._lock = Lock()
        self._timer: Timer | None = None
        self._pending_changes: dict[str, bool] = {}
        self._stopped = False
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        if self._stopped:
            self.observer = Observer()
            self._stopped = False
        self.observer.start()
        self._started = True

    def stop(self) -> None:
        self._stopped = True
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_changes.clear()
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
            if self._timer is not None:
                self._timer.cancel()
            self._timer = Timer(self.DEBOUNCE_SECONDS, self._flush_change)
            self._timer.daemon = True
            self._timer.start()

    def _flush_change(self) -> None:
        with self._lock:
            changes = self._pending_changes
            self._pending_changes = {}
            self._timer = None
            if self._stopped:
                return
        if changes:
            if not all(changes.values()):
                # Empty filename requests a full structural refresh without stale paths.
                self.on_dir_changed(False, "")
            else:
                for name in changes:
                    self.on_dir_changed(True, name)

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

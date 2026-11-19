"""REQ-008: coalescing, distinct filenames, and structural precedence in FileWatcher."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent

from doorstop_edit.utils.file_watcher import FileWatcher

# Shortened debounce keeps the test fast while preserving the quiet-period semantics.
TEST_DEBOUNCE_SECONDS = 0.02


def _wait_for_delivery(delivered: list[tuple[bool, tuple[str, ...], int]], count: int, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while len(delivered) < count:
        if time.monotonic() > deadline:
            pytest.fail(f"expected {count} watcher deliveries, got {len(delivered)}: {delivered}")
        time.sleep(0.005)


@pytest.fixture()
def watcher(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[FileWatcher, list[tuple[bool, tuple[str, ...], int]]]]:
    monkeypatch.setattr(FileWatcher, "DEBOUNCE_SECONDS", TEST_DEBOUNCE_SECONDS)
    delivered: list[tuple[bool, tuple[str, ...], int]] = []
    file_watcher = FileWatcher(on_dir_changed=lambda *args: delivered.append(args))
    yield file_watcher, delivered
    file_watcher.stop()


def _content_change(watcher: FileWatcher, path: Path) -> None:
    watcher.on_modified(FileModifiedEvent(str(path)))


def _structural_change(watcher: FileWatcher, path: Path) -> None:
    watcher.on_created(FileCreatedEvent(str(path)))


def test_watcher_coalesces_same_file_events_within_quiet_period(
    tmp_path: Path, watcher: tuple[FileWatcher, list[tuple[bool, tuple[str, ...], int]]]
) -> None:
    file_watcher, delivered = watcher
    target = tmp_path / "REQ-001.yml"
    target.write_text("initial")
    resolved = str(target.resolve())

    # Six content-change events for the same file, all inside the quiet period.
    for _ in range(3):
        _content_change(file_watcher, target)
        _content_change(file_watcher, target)

    _wait_for_delivery(delivered, 1)
    # Let any duplicate (non-coalesced) delivery become visible.
    time.sleep(TEST_DEBOUNCE_SECONDS * 4)

    assert len(delivered) == 1
    changed, filenames, _generation = delivered[0]
    assert changed is True
    assert len(filenames) == 1
    assert filenames.count(resolved) == 1

    # A later event outside the quiet period is delivered separately.
    _content_change(file_watcher, target)
    _wait_for_delivery(delivered, 2)
    time.sleep(TEST_DEBOUNCE_SECONDS * 4)
    assert len(delivered) == 2
    assert delivered[1][0] is True
    assert delivered[1][1] == (resolved,)


def test_watcher_delivers_distinct_content_change_filenames(
    tmp_path: Path, watcher: tuple[FileWatcher, list[tuple[bool, tuple[str, ...], int]]]
) -> None:
    file_watcher, delivered = watcher
    first = tmp_path / "REQ-001.yml"
    second = tmp_path / "REQ-002.yml"
    first.write_text("one")
    second.write_text("two")

    _content_change(file_watcher, first)
    _content_change(file_watcher, second)
    _content_change(file_watcher, first)  # duplicate within the quiet period

    _wait_for_delivery(delivered, 1)
    time.sleep(TEST_DEBOUNCE_SECONDS * 4)

    assert len(delivered) == 1
    changed, filenames, _generation = delivered[0]
    assert changed is True
    assert set(filenames) == {str(first.resolve()), str(second.resolve())}
    assert len(filenames) == len(set(filenames))


def test_watcher_structural_refresh_takes_precedence_in_mixed_batch(
    tmp_path: Path, watcher: tuple[FileWatcher, list[tuple[bool, tuple[str, ...], int]]]
) -> None:
    file_watcher, delivered = watcher
    content_file = tmp_path / "REQ-001.yml"
    structural_file = tmp_path / "REQ-NEW.yml"
    content_file.write_text("content")

    _content_change(file_watcher, content_file)
    _structural_change(file_watcher, structural_file)

    _wait_for_delivery(delivered, 1)
    time.sleep(TEST_DEBOUNCE_SECONDS * 4)

    assert len(delivered) == 1
    changed, filenames, _generation = delivered[0]
    assert changed is False  # structural refresh, not a content reload
    assert set(filenames) == {str(content_file.resolve()), str(structural_file.resolve())}

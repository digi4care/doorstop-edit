import json
import threading
from pathlib import Path

import pytest

from doorstop_edit import crash_log


def test_record_is_disabled_without_environment_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "crash.log"
    monkeypatch.delenv("DOORSTOP_EDIT_CRASH_LOG", raising=False)
    crash_log.record("test.event")
    assert not path.exists()


def test_record_appends_complete_metadata_records_concurrently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "crash.log"
    monkeypatch.setenv("DOORSTOP_EDIT_CRASH_LOG", str(path))
    count = 8

    def record_many(index: int) -> None:
        for item_count in range(20):
            crash_log.record("test.event", index=index, count=item_count)

    threads = [threading.Thread(target=record_many, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == count * 20
    assert all(record["event"] == "test.event" for record in records)
    assert all(record["pid"] and record["native_thread_id"] for record in records)
    assert all(record["timestamp"] and record["monotonic_ns"] for record in records)
    assert all("index" in record and "count" in record for record in records)

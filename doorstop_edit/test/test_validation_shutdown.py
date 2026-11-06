import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from doorstop_edit.validation_service import ValidationRunResult

_CHILD_RUNNER = r"""
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication
from doorstop_edit.application import DoorstopEdit

root = Path(sys.argv[1])
sentinel = Path(sys.argv[2])
app = QApplication([])
editor = DoorstopEdit(root)
editor.validation_service.request(root, editor.doorstop_data.content_revision)
deadline = time.monotonic() + 8
while not sentinel.exists() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
if not sentinel.exists():
    print("validator_started False", flush=True)
    editor.quit()
    raise SystemExit(4)
print("validator_started True", flush=True)
service = editor.validation_service
run = service._active
if run is None or run.phase != "running":
    print("validation_helper_running False", flush=True)
    editor.quit()
    raise SystemExit(5)
grace_deadline = time.monotonic() + 0.4
while time.monotonic() < grace_deadline:
    app.processEvents()
    time.sleep(0.01)
if service._active is not run or run.phase != "running":
    print("validator_still_running False", flush=True)
    editor.quit()
    raise SystemExit(6)
print("validation_helper_running True", flush=True)
print("validator_still_running True", flush=True)
result_directory = run.temp_dir
result_directory_ready = result_directory.exists() and result_directory.is_dir()
print(f"validation_result_directory_ready {result_directory_ready}", flush=True)
if not result_directory_ready:
    editor.quit()
    raise SystemExit(9)
editor.quit()
run.cleanup_event.wait(5)
app.processEvents()
process_reaped = run.owner.supervisor_reaped
print(f"validation_helper_reaped {process_reaped}", flush=True)
if not process_reaped:
    raise SystemExit(7)
result_directory_retained = result_directory.exists()
print(f"validation_result_directory_retained {result_directory_retained}", flush=True)
if not result_directory_retained:
    raise SystemExit(8)
print("shutdown_returned", flush=True)
"""


def _make_blocking_validator_project(root: Path) -> None:
    document = root / "REQ-A"
    document.mkdir(parents=True)
    (document / ".doorstop.yml").write_text(
        "settings:\n  digits: 3\n  prefix: REQ-A\n  sep: '-'\nextensions:\n  item_validator: validator.py\n",
        encoding="utf-8",
    )
    (document / "REQ-A-001.yml").write_text(
        "active: true\nheader: Blocking validator fixture\nlevel: '1'\nlinks: []\n"
        "normative: true\ntext: Fixture item\n",
        encoding="utf-8",
    )
    (document / "validator.py").write_text(
        "import os\n"
        "import time\n"
        "from pathlib import Path\n\n"
        "def item_validator(item):\n"
        "    Path(os.environ['VALIDATOR_SENTINEL']).write_text('started', encoding='utf-8')\n"
        "    while True:\n"
        "        time.sleep(1)\n",
        encoding="utf-8",
    )


def _kill_process_tree(process: Popen[str]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.kill()


def _run_with_tree_watchdog(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> str:
    child = Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        start_new_session=os.name != "nt",
        creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0,
    )
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except TimeoutExpired as exc:
        _kill_process_tree(child)
        stdout, stderr = child.communicate(timeout=5)
        raise AssertionError(f"watchdog timed out after {timeout}s; stdout={stdout!r}; stderr={stderr!r}") from exc
    returncode = child.returncode
    assert returncode == 0, f"child exit code {returncode}; stdout={stdout!r}; stderr={stderr!r}"
    return (stdout or "") + (stderr or "")


def test_quit_returns_with_genuinely_blocked_custom_validator(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _make_blocking_validator_project(project)
    sentinel = tmp_path / "validator.started"
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["VALIDATOR_SENTINEL"] = str(sentinel)
    repository_root = Path(__file__).resolve().parents[2]

    started = time.monotonic()
    output = _run_with_tree_watchdog(
        [sys.executable, "-c", _CHILD_RUNNER, str(project), str(sentinel)],
        cwd=repository_root,
        env=environment,
        timeout=12,
    )
    elapsed = time.monotonic() - started

    assert sentinel.is_file(), output
    assert "validator_started True" in output, output
    assert "validation_helper_running True" in output, output
    assert "validator_still_running True" in output, output
    assert "validation_helper_reaped True" in output, output
    assert "validation_result_directory_ready True" in output, output
    assert "validation_result_directory_retained True" in output, output
    assert "shutdown_returned" in output, output
    assert elapsed < 8, f"bounded shutdown took {elapsed:.2f}s"


_DESCENDANT_RUNNER = r"""
import os, sys, time
from pathlib import Path
from typing import Any
from PySide6.QtWidgets import QApplication
from doorstop_edit.validation_service import ValidationService
root, sentinel = Path(sys.argv[1]), Path(sys.argv[2])
app = QApplication([])
service = ValidationService()
service.request(root, 7)
deadline = time.monotonic() + 8
while not sentinel.exists() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
if not sentinel.exists(): raise SystemExit('validator readiness timeout')
helper_pid, child_pid = map(int, sentinel.read_text().split())
run = service._active
if run is None: raise SystemExit('validation run missing')
temp = run.temp_dir
if len(sys.argv) > 3 and sys.argv[3] == 'direct':
    import doorstop_edit.validation_service as module
    module.os.killpg = lambda pgid, sig: os.kill(pgid, sig)
service.shutdown()
run.cleanup_event.wait(5)
app.processEvents()
limit = time.monotonic() + 3
def gone(pid):
    try: os.kill(pid, 0)
    except ProcessLookupError: return True
    if sys.platform.startswith('linux'):
        try: return Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z'
        except FileNotFoundError: return True
    return False
if len(sys.argv) > 3 and sys.argv[3] == 'direct':
    print(f'direct_only_left_descendant {not gone(child_pid)}', flush=True)
    for pid in (helper_pid, child_pid):
        try: os.kill(pid, 9)
        except ProcessLookupError: pass
    raise SystemExit(0)
while time.monotonic() < limit and (not gone(helper_pid) or not gone(child_pid) or temp.exists()): time.sleep(.02)
print(f'helper_gone {gone(helper_pid)} child_gone {gone(child_pid)} temp_retained {temp.exists()}', flush=True)
raise SystemExit(0 if gone(helper_pid) and gone(child_pid) and temp.exists() else 1)
"""


def _make_descendant_project(root: Path, sentinel: Path) -> None:
    _make_blocking_validator_project(root)
    (root / "REQ-A" / "validator.py").write_text(
        "import os, subprocess, sys, time\nfrom pathlib import Path\n"
        "def item_validator(item):\n"
        " child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f" Path({str(sentinel)!r}).write_text(f'{{os.getpid()}} {{child.pid}}')\n"
        " while True: time.sleep(1)\n",
        encoding="utf-8",
    )


def test_shutdown_kills_custom_validator_descendant(tmp_path: Path) -> None:
    project, sentinel = tmp_path / "project", tmp_path / "processes.started"
    project.mkdir()
    _make_descendant_project(project, sentinel)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        output = _run_with_tree_watchdog(
            [sys.executable, "-c", _DESCENDANT_RUNNER, str(project), str(sentinel)],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            timeout=12,
        )
        assert "helper_gone True child_gone True temp_retained True" in output, output
    finally:
        if sentinel.exists():
            try:
                _, child_pid = map(int, sentinel.read_text().split())
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(child_pid), "/T", "/F"], timeout=5, capture_output=True, check=False
                    )
                else:
                    os.kill(child_pid, signal.SIGKILL)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass


_CRASH_LOG_RUNNER = r"""
import sys, time
from pathlib import Path
from typing import Any
from PySide6.QtWidgets import QApplication
from doorstop_edit.validation_service import ValidationService
root, sentinel = Path(sys.argv[1]), Path(sys.argv[2])
app = QApplication([]); service = ValidationService(); service.request(root, 9)
deadline = time.monotonic() + 8
while not sentinel.exists() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
if not sentinel.exists(): raise SystemExit('validator readiness timeout')
deadline = time.monotonic() + 8
while service._active is not None and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
service.shutdown()
"""


def test_crash_log_records_validation_lifecycle_without_private_data(tmp_path: Path) -> None:
    project, sentinel, log = tmp_path / "project", tmp_path / "started", tmp_path / "events.jsonl"
    project.mkdir()
    _make_blocking_validator_project(project)
    (project / "REQ-A" / "validator.py").write_text(
        "import os\nfrom pathlib import Path\ndef item_validator(item):\n"
        " Path(os.environ['VALIDATOR_SENTINEL']).write_text('done')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["VALIDATOR_SENTINEL"] = str(sentinel)
    env["DOORSTOP_EDIT_CRASH_LOG"] = str(log)
    _run_with_tree_watchdog(
        [sys.executable, "-c", _CRASH_LOG_RUNNER, str(project), str(sentinel)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        timeout=12,
    )
    import json

    events = [json.loads(line) for line in log.read_text().splitlines()]
    lifecycle = [event for event in events if event.get("event", "").startswith("validation_")]
    names = {event["event"] for event in lifecycle}
    assert {"validation_helper_start", "validation_helper_exit", "validation_shutdown"} <= names
    assert all("run_id" in event and "revision" in event for event in lifecycle)
    assert all(str(project) not in json.dumps(event) for event in lifecycle)


def test_descendant_regression_detects_direct_helper_kill(tmp_path: Path) -> None:
    project, sentinel = tmp_path / "project", tmp_path / "processes.started"
    project.mkdir()
    _make_descendant_project(project, sentinel)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    output = _run_with_tree_watchdog(
        [sys.executable, "-c", _DESCENDANT_RUNNER, str(project), str(sentinel), "direct"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        timeout=12,
    )
    assert "direct_only_left_descendant True" in output, output


class _FakePosixOwner:
    def __init__(self, status: bytes | None = None, confirms: list[bool] | None = None) -> None:
        self.group_id = 12345
        self.supervisor_reaped = False
        self.events: list[str] = []
        self._status = [status] if status is not None else [None]
        self._confirms = confirms or [True]

    def read_status(self) -> bytes | None:
        if self._status:
            return self._status.pop(0)
        return None

    def signal_group(self) -> None:
        self.events.append("signal")

    def reap_supervisor(self, timeout: float = 0.5) -> object:
        if not self.supervisor_reaped:
            assert self.events[-1] == "signal"
        self.events.append("reap")
        self.supervisor_reaped = True
        return type("Reap", (), {"supervisor_reaped": True})()

    def confirm_group_absent(self, timeout: float = 1.0) -> bool:
        self.events.append("probe")
        if len(self._confirms) > 1:
            return self._confirms.pop(0)
        return self._confirms[0]


class _FakeWindowsOwner:
    def __init__(self) -> None:
        self.codes = [0, 0]
        self.events: list[str] = []

    def poll_helper(self) -> int | None:
        self.events.append("poll")
        return self.codes.pop(0) if self.codes else 0

    def terminate_tree(self, timeout: float = 0.5) -> bool:
        self.events.append("terminate")
        return True

    def close(self, timeout: float = 0.5) -> bool:
        self.events.append("close")
        return True


def _fake_result(run: Any) -> None:
    payload = {
        "job_id": run.run_id,
        "revision": run.revision,
        "root": str(run.root),
        "findings": [],
    }
    run.result_path.write_text(json.dumps(payload), encoding="utf-8")


def test_service_posix_status_eof_signals_group_before_reap(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    service = ValidationService()
    service._platform = "posix"
    owner = _FakePosixOwner(b"")
    monkeypatch.setattr(service, "_launch_owner", lambda *args: owner)
    service.request(tmp_path, 1)
    run = service._active
    assert run is not None
    service._poll()
    qtbot.waitUntil(lambda: run.cleanup_event.is_set())
    qtbot.waitUntil(lambda: service._active is None)
    assert owner.events[:3] == ["signal", "reap", "probe"]
    assert run.temp_dir.exists(), "unprocessed result directory must be retained"
    service.shutdown()


def test_service_coalesces_requests_and_retries_unconfirmed_cleanup(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    service = ValidationService()
    service._platform = "posix"
    owners: list[_FakePosixOwner] = []

    def launch(*args: object) -> _FakePosixOwner:
        owner = _FakePosixOwner(b'{"exit_code":0}\n')
        owners.append(owner)
        return owner

    monkeypatch.setattr(service, "_launch_owner", launch)
    outputs: list[ValidationRunResult] = []
    service.result.connect(outputs.append)
    service.request(tmp_path, 1)
    first = service._active
    assert first is not None
    first.owner._confirms = [False, True]
    _fake_result(first)
    service.request(tmp_path, 2)
    service.request(tmp_path, 3)
    service._poll()
    qtbot.waitUntil(lambda: not first.cleanup_inflight and first.published)
    assert first.temp_dir.exists()
    assert len(owners) == 1, "pending request must wait for containment confirmation"
    service._poll()
    qtbot.waitUntil(lambda: service._active is not first)
    assert len(owners) == 2
    terminal = [item for item in outputs if item.state != "running"]
    assert len(terminal) == 1 and terminal[0].state == "failed"
    assert terminal[0].error == "Validation process cleanup could not be confirmed"
    assert not first.temp_dir.exists()
    service.shutdown()
    active = service._active
    if active is not None:
        qtbot.waitUntil(lambda: active.cleanup_event.is_set())
        qtbot.waitUntil(lambda: service._active is None)


def test_windows_service_uses_owner_observations_and_order(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    service = ValidationService()
    service._platform = "windows"
    owner = _FakeWindowsOwner()
    monkeypatch.setattr(service, "_launch_owner", lambda *args: owner)
    service.request(tmp_path, 5)
    run = service._active
    assert run is not None
    _fake_result(run)
    service._poll()
    qtbot.waitUntil(lambda: run.cleanup_event.is_set())
    qtbot.waitUntil(lambda: service._active is None)
    assert owner.events == ["poll", "terminate", "poll", "close"]
    service.shutdown()


def test_reentrant_terminal_result_can_request_and_shutdown(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    service = ValidationService()
    service._platform = "posix"
    owners: list[_FakePosixOwner] = []

    def launch(*args: object) -> _FakePosixOwner:
        owner = _FakePosixOwner(b'{"exit_code":0}\n')
        owners.append(owner)
        return owner

    monkeypatch.setattr(service, "_launch_owner", launch)
    service.request(tmp_path, 1)
    first = service._active
    assert first is not None
    _fake_result(first)
    callbacks = 0
    second_runs: list[Any] = []

    def on_result(result: ValidationRunResult) -> None:
        nonlocal callbacks
        if result.state == "succeeded" and callbacks == 0:
            callbacks += 1
            service.request(tmp_path, 2)
            second_runs.append(service._active)
            service.shutdown()

    service.result.connect(on_result)
    service._poll()
    qtbot.waitUntil(lambda: first.cleanup_event.is_set())
    qtbot.waitUntil(lambda: len(owners) == 2)
    second = second_runs[0]
    assert second is not None
    qtbot.waitUntil(lambda: second.cleanup_event.is_set())
    qtbot.waitUntil(lambda: service._active is None)
    service.shutdown()
    service.shutdown()
    assert service._closed


def test_repeated_shutdown_starts_only_one_cleanup_attempt(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    service = ValidationService()
    service._platform = "posix"
    owner = _FakePosixOwner()
    monkeypatch.setattr(service, "_launch_owner", lambda *args: owner)
    service.request(tmp_path, 7)
    run = service._active
    assert run is not None
    service.shutdown()
    service.shutdown()
    qtbot.waitUntil(lambda: run.cleanup_event.is_set())
    qtbot.waitUntil(lambda: service._active is None)
    assert owner.events.count("signal") == 1


def test_shutdown_windows_termination_timeout_closes_job_owner(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.validation_service import ValidationService

    class TimeoutOwner(_FakeWindowsOwner):
        def terminate_tree(self, timeout: float = 0.5) -> bool:
            self.events.append("terminate")
            return False

    service = ValidationService()
    service._platform = "windows"
    owner = TimeoutOwner()
    monkeypatch.setattr(service, "_launch_owner", lambda *args: owner)
    service.request(tmp_path, 1)
    run = service._active
    assert run is not None
    service.shutdown()
    qtbot.waitUntil(lambda: run.cleanup_event.is_set())
    assert owner.events[-2:] == ["terminate", "close"]
    assert service._active is run
    assert run.temp_dir.exists()


def test_cleanup_worker_is_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from doorstop_edit import validation_service as validation_module
    from doorstop_edit.validation_service import ValidationService

    daemon_flags: list[bool] = []
    original_thread = threading.Thread

    def tracked_thread(*args: Any, **kwargs: Any) -> threading.Thread:
        daemon_flags.append(bool(kwargs.get("daemon")))
        return original_thread(*args, **kwargs)

    monkeypatch.setattr(validation_module.threading, "Thread", tracked_thread)
    service = ValidationService()
    service._platform = "posix"
    owner = _FakePosixOwner()
    monkeypatch.setattr(service, "_launch_owner", lambda *args: owner)
    service.request(tmp_path, 1)
    run = service._active
    assert run is not None
    service.shutdown()
    assert run.cleanup_event.wait(2)
    assert daemon_flags == [True]

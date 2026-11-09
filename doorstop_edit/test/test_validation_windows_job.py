"""Windows Job Object containment tests; runtime cases execute on Windows CI."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import doorstop_edit.validation_windows_job as windows_job
from doorstop_edit.validation_windows_job import WindowsJobOwner


def _wait_for_helper_exit(owner: WindowsJobOwner, timeout: float = 10) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = owner.poll_helper()
        if code is not None:
            return code
        time.sleep(0.02)
    raise AssertionError("helper did not exit")


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object runtime test")
def test_job_retains_descendant_after_helper_exit_until_termination(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    child_code = "import os,sys,time; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(120)"
    helper_code = (
        "import subprocess,sys,time\n"
        f"child_code = {child_code!r}\n"
        "subprocess.Popen([sys.executable, '-c', child_code, sys.argv[1]])\n"
        "deadline = time.monotonic() + 8\n"
        "while not __import__('os').path.exists(sys.argv[1]) and time.monotonic() < deadline: time.sleep(.01)\n"
    )
    owner = WindowsJobOwner.launch([sys.executable, "-c", helper_code, str(marker)])
    child_handle: int | None = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.02)
        assert marker.exists(), "descendant did not publish its PID"
        child_pid = int(marker.read_text())
        child_handle = int(owner._api.OpenProcess(0x00100000 | 0x00001000, False, child_pid))
        assert child_handle, "could not open descendant process handle"
        assert owner._api.WaitForSingleObject(child_handle, 0) == windows_job._WAIT_TIMEOUT
        in_job = windows_job.wintypes.BOOL()
        assert owner._api.IsProcessInJob(child_handle, owner._job_handle, ctypes.byref(in_job))
        assert in_job.value, "intended descendant is not assigned to this Job"
        assert _wait_for_helper_exit(owner) == 0

        # Terminate and observe helper exit first. Keep the descendant process
        # handle only long enough to prove that exact process reached signaled.
        assert owner.terminate_job(timeout=5)
        assert owner._api.WaitForSingleObject(child_handle, 5000) == windows_job._WAIT_OBJECT_0
        assert owner._api.CloseHandle(child_handle)
        child_handle = None
        assert owner.wait_for_empty(timeout=5)
        assert owner.active_processes() == 0
    finally:
        if child_handle is not None:
            owner._api.CloseHandle(child_handle)
        owner.close(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object runtime test")
def test_console_helper_runs_without_console_window(tmp_path: Path) -> None:
    code = (
        "import ctypes,sys; "
        "f=ctypes.windll.kernel32.GetConsoleWindow; f.restype=ctypes.c_void_p; "
        "open(sys.argv[1],'w').write(str(f() or 0))"
    )
    # CREATE_NO_WINDOW is the documented console-application flag; stdio is
    # redirected to NUL with an explicit HANDLE_LIST, so no parent handles leak.
    marker = tmp_path / "console-window.txt"
    owner = WindowsJobOwner.launch([sys.executable, "-c", code, str(marker)])
    try:
        assert _wait_for_helper_exit(owner) == 0
        assert marker.read_text() == "0"
    finally:
        marker.unlink(missing_ok=True)
        owner.close(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object runtime test")
def test_blocked_helper_shutdown_terminates_job(tmp_path: Path) -> None:
    del tmp_path
    owner = WindowsJobOwner.launch([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert owner.poll_helper() is None
        assert owner.close(timeout=5)
    finally:
        owner.close(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object runtime test")
def test_attribute_failure_fails_closed_and_closes_job_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    api = windows_job._load_api()
    closed: list[int] = []
    created_jobs: list[int] = []
    close_handle = api.CloseHandle
    create_job = api.CreateJobObjectW

    def track_close(handle: Any) -> Any:
        closed.append(int(handle))
        return close_handle(handle)

    def track_job(*args: Any) -> Any:
        handle = create_job(*args)
        created_jobs.append(int(handle))
        return handle

    api.CloseHandle = track_close
    api.CreateJobObjectW = track_job
    api.UpdateProcThreadAttribute = lambda *args: False
    monkeypatch.setattr(windows_job, "_load_api", lambda: api)
    monkeypatch.setattr(windows_job.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Popen fallback used"))
    with pytest.raises(OSError, match="UpdateProcThreadAttribute"):
        WindowsJobOwner.launch([sys.executable, "-c", "pass"])
    assert len(created_jobs) == 1
    assert len(closed) == 4, "Job and all three temporary NUL handles must be closed"
    assert closed[-1] == created_jobs[0], "Job must close after temporary stdio handles"


def test_non_windows_launch_fails_closed() -> None:
    if os.name == "nt":
        pytest.skip("platform-specific unsupported check")
    with pytest.raises(OSError, match="validation is disabled"):
        WindowsJobOwner.launch([sys.executable, "-c", "pass"])


def test_terminate_waits_and_closes_helper_before_job_accounting() -> None:
    events: list[str] = []

    def wait_for_helper(handle: int, milliseconds: int) -> int:
        assert handle == 11
        assert milliseconds >= 0
        events.append("wait_helper")
        return windows_job._WAIT_OBJECT_0

    def get_exit_code(handle: int, output: Any) -> bool:
        assert handle == 11
        ctypes.cast(output, ctypes.POINTER(windows_job.wintypes.DWORD)).contents.value = 23
        events.append("get_exit_code")
        return True

    def close_handle(handle: int) -> bool:
        events.append(f"close_{handle}")
        return True

    def terminate_job(handle: int, exit_code: int) -> bool:
        assert (handle, exit_code) == (22, 1)
        events.append("terminate_job")
        return True

    def query_job(handle: int, info_class: int, output: Any, size: int, returned: Any) -> bool:
        assert handle == 22
        accounting = ctypes.cast(output, ctypes.POINTER(windows_job._JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)).contents
        accounting.ActiveProcesses = 0
        events.append("query_job")
        return True

    fake_api = SimpleNamespace(
        WaitForSingleObject=wait_for_helper,
        GetExitCodeProcess=get_exit_code,
        CloseHandle=close_handle,
        TerminateJobObject=terminate_job,
        QueryInformationJobObject=query_job,
    )
    owner = WindowsJobOwner(fake_api, 22, 11)  # type: ignore[arg-type]

    assert owner.terminate_tree(timeout=1)
    assert events == ["terminate_job", "wait_helper", "get_exit_code", "close_11", "query_job"]
    assert owner.poll_helper() == 23


def test_helper_wait_timeout_retains_handle_and_close_stays_unconfirmed() -> None:
    events: list[str] = []

    def wait_timeout(handle: int, milliseconds: int) -> int:
        events.append("wait_helper")
        return windows_job._WAIT_TIMEOUT

    def terminate_job(handle: int, exit_code: int) -> bool:
        events.append("terminate_job")
        return True

    def close_handle(handle: int) -> bool:
        events.append(f"close_{handle}")
        return True

    fake_api = SimpleNamespace(
        WaitForSingleObject=wait_timeout,
        TerminateJobObject=terminate_job,
        CloseHandle=close_handle,
    )
    owner = WindowsJobOwner(fake_api, 22, 11)  # type: ignore[arg-type]
    assert not owner.terminate_tree(timeout=0)
    assert owner._process_handle == 11
    assert "query_job" not in events

    assert not owner.close(timeout=0)
    assert owner._process_handle == 11, "timed-out helper handle must remain owned"
    assert owner._job_handle is None, "Job is closed last to invoke KILL_ON_JOB_CLOSE"
    assert events[-1] == "close_22"


def test_poll_helper_surfaces_wait_failed_as_api_error() -> None:
    fake_api = SimpleNamespace(
        WaitForSingleObject=lambda handle, timeout: 0xFFFFFFFF,
        GetExitCodeProcess=lambda handle, output: True,
        CloseHandle=lambda handle: True,
    )
    owner = WindowsJobOwner(fake_api, 22, 11)  # type: ignore[arg-type]
    with pytest.raises(OSError, match=r"WaitForSingleObject\(helper\)"):
        owner.poll_helper()
    assert owner._process_handle == 11
    assert not owner._helper_exited


def test_termination_api_error_is_unconfirmed_without_job_query() -> None:
    events: list[str] = []

    def wait_failed(handle: int, timeout: int) -> int:
        events.append("wait_failed")
        return 0xFFFFFFFF

    def terminate_job(handle: int, code: int) -> bool:
        events.append("terminate")
        return True

    def query_job(*args: Any) -> bool:
        events.append("query")
        return True

    fake_api = SimpleNamespace(
        WaitForSingleObject=wait_failed,
        TerminateJobObject=terminate_job,
        QueryInformationJobObject=query_job,
    )
    owner = WindowsJobOwner(fake_api, 22, 11)  # type: ignore[arg-type]
    assert not owner.terminate_tree(timeout=1)
    assert events == ["terminate", "wait_failed"]
    assert owner._process_handle == 11


def test_close_retry_swallows_wait_error_then_reaps_without_confirmation() -> None:
    wait_results = iter([windows_job._WAIT_TIMEOUT, 0xFFFFFFFF, windows_job._WAIT_OBJECT_0])
    closed: list[int] = []

    def wait_helper(handle: int, timeout: int) -> int:
        assert handle == 11
        return next(wait_results)

    def get_exit_code(handle: int, output: Any) -> bool:
        ctypes.cast(output, ctypes.POINTER(windows_job.wintypes.DWORD)).contents.value = 19
        return True

    def close_handle(handle: int) -> bool:
        closed.append(handle)
        return True

    def terminate_job(handle: int, code: int) -> bool:
        return True

    fake_api = SimpleNamespace(
        WaitForSingleObject=wait_helper,
        GetExitCodeProcess=get_exit_code,
        CloseHandle=close_handle,
        TerminateJobObject=terminate_job,
    )
    owner = WindowsJobOwner(fake_api, 22, 11)  # type: ignore[arg-type]

    assert not owner.close(timeout=0)
    assert owner._job_handle is None
    assert owner._process_handle == 11
    assert closed == [22]
    assert not owner.close(timeout=0), "WAIT_FAILED must remain unconfirmed, not escape"
    assert owner._process_handle == 11
    assert not owner.close(timeout=0), "later reap cannot upgrade prior unconfirmed cleanup"
    assert owner.poll_helper() == 19
    assert not owner._termination_confirmed
    assert closed == [22, 11]


def test_close_after_confirmed_termination_only_closes_handles() -> None:
    events: list[str] = []

    def close_handle(handle: int) -> bool:
        events.append(f"close_{handle}")
        return True

    def terminate_job(handle: int, code: int) -> bool:
        events.append("terminate")
        return True

    owner = WindowsJobOwner(
        SimpleNamespace(CloseHandle=close_handle, TerminateJobObject=terminate_job),  # type: ignore[arg-type]
        22,
        11,
    )
    owner._helper_exited = True
    owner._helper_exit_code = 0
    owner._process_handle = None
    owner._termination_confirmed = True
    assert owner.close(timeout=0)
    assert events == ["close_22"]

"""Focused POSIX tests for isolated validation containment."""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from doorstop_edit import validation_posix_supervisor as supervisor_module
from doorstop_edit.validation_posix_supervisor import PosixLaunchError, PosixValidationOwner

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics only")


HELPER = r"""
import os, subprocess, sys, time
from pathlib import Path
from typing import Any
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])
Path(sys.argv[1]).write_text(f'{os.getpid()} {child.pid}', encoding='ascii')
mode = sys.argv[2]
release = Path(sys.argv[3])
if mode != 'blocked':
    while not release.exists(): time.sleep(0.01)
if mode == 'blocked':
    while True: time.sleep(1)
if mode == 'crash':
    os._exit(17)
# normal exit with a live child
"""


def _pids(owner: PosixValidationOwner, marker: Path) -> tuple[int, int]:
    limit = time.monotonic() + 8
    while time.monotonic() < limit:
        if marker.exists():
            try:
                values = tuple(map(int, marker.read_text().split()))
            except ValueError:
                values = ()
            if len(values) == 2:
                return values
        time.sleep(0.01)
    owner.shutdown()
    raise AssertionError("helper did not start descendant")


# Linux can identify orphaned zombies via /proc; macOS process-existence checks
# cannot distinguish a live process from a zombie, so those assertions are weaker.
def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    if platform.system() == "Linux":
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except FileNotFoundError:
            return True
    return False


def _wait_gone(owner: PosixValidationOwner, pids: tuple[int, int]) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not all(_gone(pid) for pid in pids):
        time.sleep(0.02)
    assert all(_gone(pid) for pid in pids), f"processes remain: {pids}"
    result = owner.shutdown(timeout=1)
    assert result.supervisor_reaped, "supervisor reap was not confirmed"
    assert result.group_cleanup_confirmed is None, "leader reap cannot confirm group cleanup"


def _launch(
    owners: list[PosixValidationOwner], tmp_path: Path, mode: str
) -> tuple[PosixValidationOwner, Path, tuple[int, int]]:
    marker = tmp_path / "started"
    release = tmp_path / "release"
    owner = PosixValidationOwner.launch([sys.executable, "-c", HELPER, str(marker), mode, str(release)])
    owners.append(owner)
    pids = _pids(owner, marker)
    assert not _gone(pids[0]), "helper was not demonstrably live"
    assert not _gone(pids[1]), "child was not demonstrably live"
    if mode != "blocked":
        release.touch()
    return owner, marker, pids


def test_blocked_helper_shutdown_kills_helper_and_descendant(
    owners: list[PosixValidationOwner], tmp_path: Path
) -> None:
    owner, _, pids = _launch(owners, tmp_path, "blocked")
    result = owner.shutdown(timeout=1)
    assert result.supervisor_reaped
    assert result.group_cleanup_confirmed is None
    assert all(_gone(pid) for pid in pids)


@pytest.mark.parametrize("mode", ["normal", "crash"])
def test_helper_exit_kills_live_descendant(owners: list[PosixValidationOwner], tmp_path: Path, mode: str) -> None:
    owner, _, pids = _launch(owners, tmp_path, mode)
    deadline = time.monotonic() + 5
    status = b""
    while time.monotonic() < deadline and b"\n" not in status:
        chunk = owner.read_status()
        if chunk is not None:
            status += chunk
        time.sleep(0.02)
    assert b"\n" in status, "supervisor did not report helper status"
    expected_exit_code = 0 if mode == "normal" else 17
    assert json.loads(status.splitlines()[0])["exit_code"] == expected_exit_code
    # Never poll/wait on the leader before group termination; status alone does
    # not establish completed descendant cleanup.
    owner.signal_group()
    _wait_gone(owner, pids)


def test_gui_eof_terminates_group(owners: list[PosixValidationOwner], tmp_path: Path) -> None:
    owner, _, pids = _launch(owners, tmp_path, "blocked")
    owner.close_gui_pipe()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not all(_gone(pid) for pid in pids):
        time.sleep(0.02)
    assert all(_gone(pid) for pid in pids)
    result = owner.shutdown(timeout=1)
    assert result.supervisor_reaped
    assert result.group_cleanup_confirmed is None


def test_supervisor_crash_then_gui_group_signal_cleans_descendant(
    owners: list[PosixValidationOwner], tmp_path: Path
) -> None:
    owner, _, pids = _launch(owners, tmp_path, "blocked")
    # No bytes yet is distinct from EOF while supervisor is alive.
    assert owner.read_status() is None
    # Simulate supervisor death; do not reap it before signaling its retained PGID.
    os.kill(owner.process.pid, signal.SIGKILL)
    deadline = time.monotonic() + 3
    eof = False
    while time.monotonic() < deadline:
        chunk = owner.read_status()
        if chunk == b"":
            eof = True
            break
        time.sleep(0.01)
    assert eof, "supervisor crash did not produce status-pipe EOF"
    owner.signal_group()
    result = owner.reap_supervisor(timeout=1)
    assert result.supervisor_reaped
    assert result.group_cleanup_confirmed is None
    assert owner.status_fd == -1
    assert owner.gui_write_fd == -1
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not all(_gone(pid) for pid in pids):
        time.sleep(0.02)
    assert all(_gone(pid) for pid in pids)


def test_direct_helper_kill_is_not_descendant_containment(owners: list[PosixValidationOwner], tmp_path: Path) -> None:
    owner, _, pids = _launch(owners, tmp_path, "blocked")
    try:
        os.kill(pids[0], signal.SIGKILL)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and _gone(pids[1]):
            time.sleep(0.01)
        assert not _gone(pids[1]), "direct helper kill unexpectedly removed descendant"
    finally:
        owner.shutdown(timeout=1)
    assert all(_gone(pid) for pid in pids)


@pytest.fixture
def owners(request: pytest.FixtureRequest) -> list[PosixValidationOwner]:
    active: list[PosixValidationOwner] = []

    def cleanup() -> None:
        for owner in reversed(active):
            owner.shutdown(timeout=1)

    request.addfinalizer(cleanup)
    return active


def test_shutdown_timeout_retains_owner_and_allows_reap_retry(
    owners: list[PosixValidationOwner], tmp_path: Path
) -> None:
    owner, _, _ = _launch(owners, tmp_path, "blocked")
    original_wait = owner.process.wait
    calls = 0

    def wait_with_one_timeout(timeout: float | None = None) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(owner.process.args, timeout if timeout is not None else 0.0)
        return original_wait(timeout=timeout)

    owner.process.wait = wait_with_one_timeout  # type: ignore[method-assign]
    first = owner.shutdown(timeout=0.01)
    assert not first.supervisor_reaped
    assert owner.process.returncode is None
    assert owner.status_fd >= 0
    assert owner.gui_write_fd == -1
    second = owner.shutdown(timeout=1)
    assert second.supervisor_reaped
    assert second.group_cleanup_confirmed is None
    assert owner.status_fd == -1


def test_post_spawn_setup_failure_signals_and_reaps_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure closing a parent pipe after Popen must not orphan the group."""
    original_popen = supervisor_module.subprocess.Popen
    original_close = os.close
    original_killpg = os.killpg
    events: list[str] = []
    spawned = False
    injected = False
    pipe_pairs: list[tuple[int, int]] = []
    original_pipe = os.pipe

    def tracked_pipe() -> tuple[int, int]:
        pair = original_pipe()
        pipe_pairs.append(pair)
        return pair

    def tracked_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        nonlocal spawned
        process = original_popen(*args, **kwargs)
        spawned = True
        return process

    original_reap = PosixValidationOwner.reap_supervisor

    def tracked_reap(owner: PosixValidationOwner, timeout: float = 0.5) -> object:
        events.append("wait")
        return original_reap(owner, timeout)

    def fail_first_parent_close(fd: int) -> None:
        nonlocal injected
        if spawned and not injected:
            injected = True
            raise OSError("injected post-spawn close failure")
        original_close(fd)

    def tracked_killpg(pgid: int, sig: int) -> None:
        if sig == signal.SIGKILL:
            events.append("signal")
        original_killpg(pgid, sig)

    monkeypatch.setattr(supervisor_module.os, "pipe", tracked_pipe)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(PosixValidationOwner, "reap_supervisor", tracked_reap)
    monkeypatch.setattr(supervisor_module.os, "close", fail_first_parent_close)
    monkeypatch.setattr(supervisor_module.os, "killpg", tracked_killpg)

    with pytest.raises(PosixLaunchError) as error:
        PosixValidationOwner.launch([sys.executable, "-c", "import time; time.sleep(30)"])

    owner = error.value.owner
    assert injected
    assert owner.supervisor_reaped
    assert events.index("signal") < events.index("wait")
    assert owner.confirm_group_absent(timeout=1)
    assert owner.status_fd == -1
    assert owner.gui_write_fd == -1
    for fd in (pipe_pairs[0][1], pipe_pairs[1][0]):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_pre_spawn_setup_failure_closes_all_pipes(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe_pairs: list[tuple[int, int]] = []
    original_pipe = os.pipe

    def tracked_pipe() -> tuple[int, int]:
        pair = original_pipe()
        pipe_pairs.append(pair)
        return pair

    def fail_set_blocking(fd: int, blocking: bool) -> None:
        raise OSError("injected pre-spawn setup failure")

    monkeypatch.setattr(supervisor_module.os, "pipe", tracked_pipe)
    monkeypatch.setattr(supervisor_module.os, "set_blocking", fail_set_blocking)

    with pytest.raises(OSError, match="injected pre-spawn setup failure"):
        PosixValidationOwner.launch([sys.executable, "-c", "pass"])

    assert len(pipe_pairs) == 2
    for fd in (fd for pair in pipe_pairs for fd in pair):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_reaped_supervisor_retains_and_retries_descriptor_close(
    owners: list[PosixValidationOwner], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    owner, _, _ = _launch(owners, tmp_path, "blocked")
    status_fd = owner.status_fd
    original_close = os.close
    injected = False

    def fail_first_status_close(fd: int) -> None:
        nonlocal injected
        if fd == status_fd and not injected:
            injected = True
            raise OSError("injected descriptor close failure")
        original_close(fd)

    owner.signal_group()
    monkeypatch.setattr(supervisor_module.os, "close", fail_first_status_close)
    with pytest.raises(OSError, match="injected descriptor close failure"):
        owner.reap_supervisor(timeout=1)

    assert owner.supervisor_reaped
    assert owner.status_fd == status_fd, "failed descriptor must remain owned for retry"
    owner.reap_supervisor(timeout=0)
    assert owner.status_fd == -1
    assert owner.confirm_group_absent(timeout=1)

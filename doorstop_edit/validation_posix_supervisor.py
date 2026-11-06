"""POSIX validation process-group containment for the GUI validation service."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Sequence


def _status(fd: int, code: int | None) -> None:
    try:
        os.write(fd, (json.dumps({"exit_code": code}) + "\n").encode())
    except OSError:
        pass


def _supervise(argv: Sequence[str], status_fd: int, gui_fd: int) -> int:
    """Supervisor runs as session/group leader; helper inherits its group only."""
    with selectors.DefaultSelector() as selector:
        selector.register(gui_fd, selectors.EVENT_READ)
        helper = subprocess.Popen(
            list(argv),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        exit_code: int | None = None
        while True:
            exit_code = helper.poll()
            if exit_code is not None:
                _status(status_fd, exit_code)
                break
            if selector.select(timeout=0.05):
                if not os.read(gui_fd, 1):
                    _status(status_fd, None)
                    break
        # This is intentionally the supervisor's final operation: terminate every
        # ordinary member of the group, including ourselves and the helper.
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        except ProcessLookupError:
            pass
    return 0


def _main() -> int:
    try:
        separator = sys.argv.index("--")
        status_fd, gui_fd = int(sys.argv[1]), int(sys.argv[2])
        argv = sys.argv[separator + 1 :]
        if not argv:
            return 2
        return _supervise(argv, status_fd, gui_fd)
    except (ValueError, IndexError):
        return 2


@dataclass(frozen=True)
class PosixCleanupResult:
    """Observed cleanup state; group cleanup is not inferred from leader reap."""

    supervisor_reaped: bool
    group_cleanup_confirmed: bool | None = None


class PosixLaunchError(OSError):
    """Launch setup failed after spawn; carries the owner for bounded retry cleanup."""

    def __init__(self, owner: "PosixValidationOwner", cause: BaseException) -> None:
        super().__init__("POSIX validation launch setup failed")
        self.owner = owner
        self.__cause__ = cause


@dataclass
class PosixValidationOwner:
    """One-run owner for supervisor anchor and its private control pipes."""

    process: subprocess.Popen[bytes]
    status_fd: int
    gui_write_fd: int
    group_id: int
    _kill_requested: bool = False
    supervisor_reaped: bool = False
    extra_fds: list[int] = field(default_factory=list)

    @classmethod
    def launch(cls, argv: Sequence[str]) -> "PosixValidationOwner":
        if os.name == "nt":
            raise OSError("POSIX validation containment is unavailable on Windows")
        pipe_fds: list[int] = []
        try:
            status_r, status_w = os.pipe()
            pipe_fds.extend((status_r, status_w))
            gui_r, gui_w = os.pipe()
            pipe_fds.extend((gui_r, gui_w))
            os.set_blocking(status_r, False)
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "doorstop_edit.validation_posix_supervisor",
                    str(status_w),
                    str(gui_r),
                    "--",
                    *argv,
                ],
                close_fds=True,
                pass_fds=(status_w, gui_r),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except BaseException:
            for fd in pipe_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise
        owner = cls(proc, status_r, gui_w, proc.pid, extra_fds=[status_w, gui_r])
        try:
            owner.close_child_fds()
            return owner
        except BaseException as exc:
            # Retry closing both child-side descriptors if a close itself failed.
            # Then signal the entire group before any possible wait/reap. If this
            # bounded attempt cannot finish, the exception preserves ownership.
            try:
                owner.close_child_fds()
            except OSError:
                pass
            try:
                owner.signal_group()
                owner.close_gui_pipe()
                owner.reap_supervisor(timeout=0.5)
            except BaseException:
                pass
            raise PosixLaunchError(owner, exc) from None

    def read_status(self) -> bytes | None:
        """Return bytes, b'' at EOF, or None when nonblocking read has no data."""
        if self.status_fd < 0:
            return b""
        try:
            return os.read(self.status_fd, 4096)
        except BlockingIOError:
            return None

    def signal_group(self) -> None:
        """Signal while the supervisor anchor is unreaped; errors are retryable."""
        if self.supervisor_reaped:
            raise RuntimeError("Cannot signal a process group after supervisor reap")
        if self._kill_requested:
            return
        try:
            os.killpg(self.group_id, signal.SIGKILL)
        except ProcessLookupError:
            self._kill_requested = True
        else:
            self._kill_requested = True

    def close_gui_pipe(self) -> None:
        if self.gui_write_fd >= 0:
            os.close(self.gui_write_fd)
            self.gui_write_fd = -1

    def close_status_pipe(self) -> None:
        if self.status_fd >= 0:
            os.close(self.status_fd)
            self.status_fd = -1

    def close_child_fds(self) -> None:
        """Close parent copies of child-side descriptors, retaining failed closes."""
        for fd in tuple(self.extra_fds):
            os.close(fd)
            self.extra_fds.remove(fd)

    def close_pipes(self) -> None:
        """Close every owned descriptor; failures remain represented for retry."""
        self.close_status_pipe()
        self.close_gui_pipe()
        self.close_child_fds()

    def reap_supervisor(self, timeout: float = 0.5) -> PosixCleanupResult:
        """Reap only after group kill; retain descriptor ownership on close failure."""
        if not self._kill_requested:
            raise RuntimeError("process-group termination must precede supervisor reap")
        if not self.supervisor_reaped:
            try:
                self.process.wait(timeout=max(0.0, timeout))
            except subprocess.TimeoutExpired:
                return PosixCleanupResult(supervisor_reaped=False)
            self.supervisor_reaped = True
        self.close_pipes()
        return PosixCleanupResult(supervisor_reaped=True)

    def confirm_group_absent(self, timeout: float = 1.0) -> bool:
        """Confirm group absence only by post-reap signal-zero ESRCH probes."""
        if not self.supervisor_reaped or not self._kill_requested:
            return False
        import time

        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                os.killpg(self.group_id, 0)
            except ProcessLookupError:
                return True
            except OSError:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def shutdown(self, timeout: float = 0.5) -> PosixCleanupResult:
        """Bounded group termination/reap; leader reap does not confirm descendants."""
        if not self.supervisor_reaped:
            self.signal_group()
        self.close_gui_pipe()
        return self.reap_supervisor(timeout)


if __name__ == "__main__":
    raise SystemExit(_main())

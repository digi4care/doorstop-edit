"""Asynchronous validation orchestration with platform containment owners."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from doorstop_edit.crash_log import record
from doorstop_edit.doorstop_data import ValidationFinding
from doorstop_edit.validation_posix_supervisor import PosixLaunchError, PosixValidationOwner
from doorstop_edit.validation_windows_job import WindowsJobOwner

MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_STATUS_BYTES = 64 * 1024
logger = logging.getLogger("gui")


@dataclass(frozen=True)
class ValidationRunResult:
    root: str
    revision: int
    run_id: str
    findings: tuple[ValidationFinding, ...]
    state: str
    started_at: Optional[str]
    completed_at: Optional[str]
    error: Optional[str]
    project_id: str

    @property
    def content_revision(self) -> int:
        return self.revision


@dataclass
class _ValidationRun:
    run_id: str
    root: Path
    revision: int
    result_path: Path
    temp_dir: Path
    started_at: str
    owner: Any
    phase: str = "running"
    status_buffer: bytearray = field(default_factory=bytearray)
    helper_exit_code: int | None = None
    helper_completed: bool = False
    error: str | None = None
    cleanup_inflight: bool = False
    cleanup_event: threading.Event = field(default_factory=threading.Event)
    published: bool = False


@dataclass(frozen=True)
class _CleanupOutcome:
    run_id: str
    confirmed: bool
    exit_code: int | None
    findings: tuple[ValidationFinding, ...] = ()
    result_error: str | None = None
    directory_removed: bool = False
    result_processed: bool = False


class ValidationService(QObject):
    result = Signal(object)
    _cleanup_completed = Signal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._cleanup_completed.connect(self._on_cleanup_completed)
        self._active: _ValidationRun | None = None
        self._pending: tuple[Path, int] | None = None
        self._closed = False
        self._platform = "windows" if os.name == "nt" else "posix"
        self._starting = False
        self._last_identity: tuple[str, int] | None = None

    def request(self, root: Path, content_revision: int) -> None:
        if self._closed:
            return
        self._pending = (root.resolve(), content_revision)
        if self._active is None and not self._starting:
            self._start_pending()

    def _launch_owner(self, root: Path, revision: int, run_id: str, result_path: Path) -> Any:
        argv = [
            sys.executable,
            "-m",
            "doorstop_edit.validation_helper",
            str(root),
            str(revision),
            run_id,
            str(result_path),
        ]
        if self._platform == "windows":
            return WindowsJobOwner.launch(argv)
        return PosixValidationOwner.launch(argv)

    def _start_pending(self) -> None:
        if self._closed or self._pending is None or self._active is not None or self._starting:
            return
        root, revision = self._pending
        self._pending = None
        run_id = uuid.uuid4().hex
        directory = Path(tempfile.mkdtemp(prefix="doorstop-validation-"))
        result_path = directory / "result.json"
        started = datetime.now(timezone.utc).isoformat()
        self._starting = True
        try:
            owner = self._launch_owner(root, revision, run_id, result_path)
        except PosixLaunchError as exc:
            owner = exc.owner
            run = _ValidationRun(run_id, root, revision, result_path, directory, started, owner)
            run.phase = "finishing"
            run.error = "Validation process cleanup could not be confirmed"
            self._active = run
            self._starting = False
            self._schedule_cleanup(run)
            return
        except Exception as exc:
            # No owner was returned, so the run's private directory is retained:
            # containment and result processing were not both confirmed.
            record("validation_helper_exit", run_id=run_id, revision=revision, state="launch_failed")
            self._emit_result(
                ValidationRunResult(str(root), revision, run_id, (), "running", started, None, None, str(root))
            )
            self._emit_result(
                ValidationRunResult(
                    str(root),
                    revision,
                    run_id,
                    (),
                    "failed",
                    started,
                    datetime.now(timezone.utc).isoformat(),
                    str(exc),
                    str(root),
                )
            )
            self._starting = False
            self._start_pending()
            return

        run = _ValidationRun(run_id, root, revision, result_path, directory, started, owner)
        self._active = run
        self._last_identity = (run.run_id, run.revision)
        self._starting = False
        pid = owner.group_id if self._platform == "posix" else None
        record("validation_helper_start", run_id=run_id, revision=revision, state="running", pid=pid)
        self._emit_run(run, "running", (), None)
        if self._active is run and run.phase == "running":
            self._timer.start()

    def _emit_result(self, result: ValidationRunResult) -> None:
        self.result.emit(result)

    def _emit_run(
        self, run: _ValidationRun, state: str, findings: tuple[ValidationFinding, ...], error: str | None
    ) -> None:
        self._emit_result(
            ValidationRunResult(
                str(run.root),
                run.revision,
                run.run_id,
                findings,
                state,
                run.started_at,
                datetime.now(timezone.utc).isoformat(),
                error,
                str(run.root),
            )
        )

    def _poll(self) -> None:
        run = self._active
        if run is None:
            self._timer.stop()
            return
        if run.phase == "finishing":
            self._schedule_cleanup(run)
            return
        try:
            if self._platform == "windows":
                code = run.owner.poll_helper()
                if code is None:
                    return
                run.helper_exit_code = code
                run.helper_completed = True
                self._begin_finishing(run)
                return
            self._poll_posix(run)
        except Exception:
            self._begin_finishing(run, error="Validation process status could not be observed")

    def _poll_posix(self, run: _ValidationRun) -> None:
        while True:
            chunk = run.owner.read_status()
            if chunk is None:
                return
            if chunk == b"":
                self._begin_finishing(run, error="Validation supervisor exited unexpectedly")
                return
            run.status_buffer.extend(chunk)
            if len(run.status_buffer) > MAX_STATUS_BYTES:
                self._begin_finishing(run, error="Validation supervisor returned invalid status")
                return
            newline = run.status_buffer.find(b"\n")
            if newline < 0:
                continue
            try:
                status = json.loads(bytes(run.status_buffer[:newline]))
                code = status["exit_code"]
                if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
                    raise ValueError
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                self._begin_finishing(run, error="Validation supervisor returned invalid status")
                return
            run.helper_exit_code = code
            run.helper_completed = code is not None
            error = None if code is not None else "Validation helper exited unexpectedly"
            self._begin_finishing(run, error=error)
            return

    def _begin_finishing(self, run: _ValidationRun, error: str | None = None) -> None:
        if self._active is not run or run.phase != "running":
            return
        run.phase = "finishing"
        run.error = error
        self._timer.stop()
        self._schedule_cleanup(run)

    def _schedule_cleanup(self, run: _ValidationRun) -> None:
        if run.cleanup_inflight or self._active is not run:
            return
        run.cleanup_inflight = True
        run.cleanup_event.clear()

        def worker() -> None:
            try:
                outcome = self._cleanup_run(run)
            except Exception:
                outcome = _CleanupOutcome(run.run_id, False, run.helper_exit_code)
            finally:
                run.cleanup_event.set()
            self._cleanup_completed.emit(outcome)

        # Cleanup is bounded while the GUI runs, but a blocked native/filesystem
        # call must not keep interpreter shutdown alive. Process exit is only a
        # fallback: POSIX GUI-pipe EOF triggers group kill; Windows closes the
        # final Job handle and KILL_ON_JOB_CLOSE activates. It is not confirmation.
        thread = threading.Thread(target=worker, name=f"validation-cleanup-{run.run_id}", daemon=True)
        thread.start()

    def _cleanup_run(self, run: _ValidationRun) -> _CleanupOutcome:
        owner = run.owner
        if self._platform == "windows":
            if not owner.terminate_tree(timeout=0.5):
                # During normal cleanup retain the Job for retries. On shutdown,
                # closing it is the OS-level KILL_ON_JOB_CLOSE fallback.
                if self._closed:
                    owner.close(timeout=0.0)
                return _CleanupOutcome(run.run_id, False, run.helper_exit_code)
            code = owner.poll_helper()
            closed = owner.close(timeout=0.0)
            if not closed:
                return _CleanupOutcome(run.run_id, False, code)
            run.helper_exit_code = code
            run.helper_completed = True
        else:
            if not owner.supervisor_reaped:
                owner.signal_group()
            # Reap also retries closure of every owned descriptor when the
            # supervisor was already reaped but a prior close failed.
            reaped = owner.reap_supervisor(timeout=0.5)
            if not reaped.supervisor_reaped:
                return _CleanupOutcome(run.run_id, False, run.helper_exit_code)
            if not owner.confirm_group_absent(timeout=1.0):
                return _CleanupOutcome(run.run_id, False, run.helper_exit_code)

        findings: tuple[ValidationFinding, ...] = ()
        result_error: str | None = None
        result_processed = run.helper_completed
        if run.helper_completed and run.helper_exit_code == 0:
            findings, result_error = self._read_result(run)
        elif run.helper_completed:
            result_error = "Validation helper exited unexpectedly"
        elif run.error is None:
            result_error = "Validation helper exited unexpectedly"

        removed = False
        if result_processed:
            try:
                shutil.rmtree(run.temp_dir)
                removed = True
            except FileNotFoundError:
                removed = True
            except OSError:
                removed = False
        return _CleanupOutcome(
            run.run_id, True, run.helper_exit_code, findings, result_error, removed, result_processed
        )

    @staticmethod
    def _read_result(run: _ValidationRun) -> tuple[tuple[ValidationFinding, ...], str | None]:
        try:
            if not run.result_path.is_file() or run.result_path.stat().st_size > MAX_RESULT_BYTES:
                return (), "Validation helper returned no valid result"
            raw = run.result_path.read_bytes()
            if len(raw) > MAX_RESULT_BYTES:
                return (), "Validation helper returned no valid result"
            data = json.loads(raw)
            if (
                not isinstance(data, dict)
                or data.get("job_id") != run.run_id
                or data.get("revision") != run.revision
                or data.get("root") != str(run.root)
            ):
                return (), "Validation result identity mismatch"
            if "error" in data:
                return (), str(data["error"])
            return tuple(ValidationFinding(**item) for item in data["findings"]), None
        except Exception:
            return (), "Validation helper returned no valid result"

    def _on_cleanup_completed(self, outcome: _CleanupOutcome) -> None:
        run = self._active
        if run is None or run.run_id != outcome.run_id:
            return
        run.cleanup_inflight = False
        if not outcome.confirmed:
            record("validation_cleanup", run_id=run.run_id, revision=run.revision, state="cleanup_unconfirmed")
            if not run.published:
                run.published = True
                self._emit_run(run, "failed", (), "Validation process cleanup could not be confirmed")
            self._timer.start()
            return

        state = "failed" if run.error or outcome.result_error or outcome.exit_code != 0 else "succeeded"
        error = run.error or outcome.result_error
        record(
            "validation_helper_exit",
            run_id=run.run_id,
            revision=run.revision,
            state=state,
            exit_code=outcome.exit_code,
        )
        self._timer.stop()
        self._active = None
        if not run.published:
            run.published = True
            self._emit_run(run, state, outcome.findings, error)
        if not self._closed:
            self._start_pending()

    def shutdown(self) -> None:
        if not self._closed:
            self._closed = True
            self._pending = None
            self._timer.stop()
            run = self._active
            identity = (run.run_id, run.revision) if run is not None else self._last_identity
            if identity is not None:
                record("validation_shutdown", run_id=identity[0], revision=identity[1], state="terminating")
            if run is not None:
                if run.phase == "running":
                    run.phase = "finishing"
                    run.error = run.error or "Validation stopped during shutdown"
                self._schedule_cleanup(run)
        run = self._active
        if run is not None and not run.cleanup_inflight:
            self._schedule_cleanup(run)
        if run is not None and run.cleanup_inflight:
            run.cleanup_event.wait(timeout=0.5)

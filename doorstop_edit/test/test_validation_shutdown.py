import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired

_CHILD_RUNNER = r"""
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication
from doorstop_edit.application import DoorstopEdit

root = Path(sys.argv[1])
sentinel = Path(sys.argv[2])
app = QApplication([])
editor = DoorstopEdit(root)
editor._start_validation()
deadline = time.monotonic() + 8
while not sentinel.exists() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
if not sentinel.exists():
    print("validator_started False", flush=True)
    editor.quit()
    raise SystemExit(4)
print("validator_started True", flush=True)
process = editor._validation_process
uses_helper = (
    process is not None
    and process.args[0] == sys.executable
    and "doorstop_edit.validation_helper" in process.args
)
if not uses_helper:
    print("validation_helper_running False", flush=True)
    editor.quit()
    raise SystemExit(5)
grace_deadline = time.monotonic() + 0.4
while time.monotonic() < grace_deadline:
    app.processEvents()
    time.sleep(0.01)
still_running = (
    process is editor._validation_process
    and process.poll() is None
    and editor._validation_running
)
if not still_running:
    print("validator_still_running False", flush=True)
    editor.quit()
    raise SystemExit(6)
print("validation_helper_running True", flush=True)
print("validator_still_running True", flush=True)
process = editor._validation_process
result_directory = editor._validation_temp
result_directory_ready = (
    result_directory is not None
    and result_directory.exists()
    and result_directory.is_dir()
)
print(f"validation_result_directory_ready {result_directory_ready}", flush=True)
if not result_directory_ready:
    editor.quit()
    raise SystemExit(9)
editor.quit()
process_reaped = process.poll() is not None
print(f"validation_helper_reaped {process_reaped}", flush=True)
if not process_reaped:
    raise SystemExit(7)
result_directory_removed = not result_directory.exists()
print(f"validation_result_directory_removed {result_directory_removed}", flush=True)
if not result_directory_removed:
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
        # These APIs are Unix-only; retain process-group cleanup there.
        try:
            getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
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
    assert "validation_result_directory_removed True" in output, output
    assert "shutdown_returned" in output, output
    assert elapsed < 8, f"bounded shutdown took {elapsed:.2f}s"

"""REQ-009: an isolated run of test_application.py must exit cleanly (status 0)."""

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_isolated_test_application_run_exits_zero() -> None:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "doorstop_edit/test/test_application.py", "-q"],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"isolated test_application.py run exited with {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    assert "Traceback" not in completed.stderr, completed.stderr

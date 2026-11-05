"""GUI-free subprocess entry point for project validation."""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from doorstop_edit.doorstop_data import collect_validation, configure_validation_policy

MAX_RESULT_BYTES = 4 * 1024 * 1024


def run(root: Path, revision: int, job_id: str, result_path: Path) -> None:
    try:
        configure_validation_policy()
        findings = collect_validation(root)
        result: dict[str, Any] = {
            "job_id": job_id,
            "revision": revision,
            "root": str(root),
            "findings": [
                {"severity": finding.severity, "message": finding.message, "item_uid": finding.item_uid}
                for finding in findings
            ],
        }
    except Exception as exc:
        result = {"job_id": job_id, "revision": revision, "root": str(root), "error": str(exc)}
        if not result["error"]:
            result["error"] = traceback.format_exc(limit=5)
    payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_RESULT_BYTES:
        payload = json.dumps(
            {
                "job_id": job_id,
                "revision": revision,
                "root": str(root),
                "error": "Validation result exceeded size limit",
            }
        ).encode()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=result_path.parent, prefix=".validation-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, result_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    run(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))

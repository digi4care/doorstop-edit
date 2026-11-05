"""Opt-in, best-effort diagnostics for investigating application crashes."""

import json
import os
import threading
import time
from datetime import datetime, timezone

_ENV_NAME = "DOORSTOP_EDIT_CRASH_LOG"
_lock = threading.Lock()


def record(event: str, **fields: object) -> None:
    """Append a metadata-only JSON line if crash logging is enabled."""
    path = os.environ.get(_ENV_NAME)
    if not path:
        return
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "native_thread_id": threading.get_native_id(),
        "event": event,
        **fields,
    }
    try:
        line = (json.dumps(payload, separators=(",", ":"), default=str) + "\n").encode()
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
    except Exception:
        return

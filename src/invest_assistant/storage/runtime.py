"""Single-process serialization and atomic local credential storage."""
from __future__ import annotations

import os
import tempfile
from functools import wraps
from pathlib import Path
from threading import RLock

_storage_lock = RLock()


def serialized(function):
    """Serialize shared Drive transport and complete read/modify/write operations."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _storage_lock:
            return function(*args, **kwargs)
    return wrapped


def require_private_operation() -> None:
    from invest_assistant import config
    if config.STREAMLIT_PUBLIC_MODE:
        raise PermissionError("This operation is disabled in public snapshot mode.")


def atomic_write_private(path: str, content: str) -> None:
    """Write beside the target, then replace; retain the old file on failure."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

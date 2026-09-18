"""Single-process serialization and atomic local credential storage."""
from __future__ import annotations

import os
import tempfile
from functools import wraps
from pathlib import Path
from threading import RLock

_storage_lock = RLock()
_credential_lock = RLock()
_lock_registry_guard = RLock()
_resource_locks = {}


def credential_serialized(function):
    """OAuth has its own lock: transport refresh must not acquire paper's lock."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _credential_lock:
            return function(*args, **kwargs)
    return wrapped


def resource_lock(folder: str, filename: str):
    """Single-process file transaction lock shared by independent Drive clients."""
    with _lock_registry_guard:
        return _resource_locks.setdefault((folder, filename), RLock())


def transport_serialized(function):
    """Protect one client's non-thread-safe HTTP transport, not other clients."""
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with _lock_registry_guard:
            lock = self.__dict__.setdefault('_transport_lock', RLock())
        with lock:
            return function(self, *args, **kwargs)
    return wrapped


def ticker_transaction(function):
    @wraps(function)
    def wrapped(self, ticker, *args, **kwargs):
        with resource_lock(getattr(self, 'folder_id', ''), f'{ticker}.parquet'):
            return function(self, ticker, *args, **kwargs)
    return wrapped


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

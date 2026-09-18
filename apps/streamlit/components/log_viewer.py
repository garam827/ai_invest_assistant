from __future__ import annotations

import logging
from threading import get_ident


class _StreamlitLogHandler(logging.Handler):
    """Streams log records into a Streamlit code block, throttled to avoid excessive redraws."""

    def __init__(self, placeholder, flush_every: int = 5):
        super().__init__()
        self.placeholder = placeholder
        self.flush_every = flush_every
        self.lines: list[str] = []
        self.owner_thread = get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))
        if get_ident() == self.owner_thread and len(self.lines) % self.flush_every == 0:
            self._flush()

    def _flush(self) -> None:
        if get_ident() == self.owner_thread:
            with self.lock:
                text = "\n".join(self.lines[-300:])
            self.placeholder.code(text)

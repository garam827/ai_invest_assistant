from __future__ import annotations

import logging


class _StreamlitLogHandler(logging.Handler):
    """Streams log records into a Streamlit code block, throttled to avoid excessive redraws."""

    def __init__(self, placeholder, flush_every: int = 5):
        super().__init__()
        self.placeholder = placeholder
        self.flush_every = flush_every
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))
        if len(self.lines) % self.flush_every == 0:
            self._flush()

    def _flush(self) -> None:
        self.placeholder.code("\n".join(self.lines[-300:]))

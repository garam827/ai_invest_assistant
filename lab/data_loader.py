"""Notebook helper: load a ticker's full stored OHLCV history from the Drive "DB"."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pandas as pd  # noqa: E402

from drive_db import DriveDB  # noqa: E402


def load_ticker_data(ticker: str) -> pd.DataFrame | None:
    """Return the full stored OHLCV DataFrame for `ticker` (e.g. "AAPL", "BTC-USD"), or None if it doesn't exist in Drive."""
    # client_secret.json/token.json are read via paths relative to the repo root
    # (config.py), but a notebook's cwd is wherever the .ipynb lives (lab/) -- hop over
    # to the root just for this call so DriveDB() can find them.
    cwd = os.getcwd()
    os.chdir(_ROOT)
    try:
        return DriveDB().load_ticker(ticker)
    finally:
        os.chdir(cwd)

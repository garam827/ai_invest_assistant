"""Notebook helper using the installed application package."""
from __future__ import annotations

import pandas as pd

from invest_assistant.storage.drive import DriveDB


def load_ticker_data(ticker: str) -> pd.DataFrame | None:
    """Load a ticker without changing the notebook process's working directory."""
    return DriveDB().load_ticker(ticker)

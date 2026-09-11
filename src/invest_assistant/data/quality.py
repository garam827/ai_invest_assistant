"""Shared checks before persisting prices or interpreting them as trading signals."""
from __future__ import annotations

import numpy as np
import pandas as pd


def validate_ohlcv(df: pd.DataFrame) -> None:
    columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = set(columns) - set(df.columns)
    if missing or df.empty:
        raise ValueError(f"Invalid OHLCV: empty data or missing columns {sorted(missing)}")
    prices = df[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    valid = (np.isfinite(prices).all(axis=1) & prices.gt(0).all(axis=1)
             & np.isfinite(volume) & volume.ge(0)
             & pd.to_datetime(df["Date"], errors="coerce").notna())
    if not valid.all():
        dates = df.loc[~valid, "Date"].astype(str).tail(5).tolist()
        raise ValueError(f"Invalid OHLCV: {int((~valid).sum())} rows; dates={dates}")

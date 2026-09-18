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
        invalid_fields = {}
        for column in prices:
            invalid_fields[column] = ~np.isfinite(prices[column]) | prices[column].le(0)
        invalid_fields['Volume'] = ~np.isfinite(volume) | volume.lt(0)
        invalid_fields['Date'] = pd.to_datetime(df['Date'], errors='coerce').isna()
        details = [
            {column: str(df.iloc[position][column]) for column, mask in invalid_fields.items() if mask.iloc[position]}
            for position in np.flatnonzero(~valid.to_numpy())[-5:]
        ]
        raise ValueError(f"Invalid OHLCV: {int((~valid).sum())} rows; dates={dates}; invalid_fields={details}")

"""Trailing-average comparison for display-only FX series (universe.FX_TICKERS).

Not a trading rule: no Donchian/ATR, no action. The window is anchored at the series' own
latest stored bar (or `as_of`), not today's date, so a stale collection still compares a
consistent 3-year span and the report shows which day it describes.
"""
from __future__ import annotations

import pandas as pd

from invest_assistant.universe import FX_TREND_YEARS


def compute_fx_trend(
    raw_df: pd.DataFrame | None, as_of: str | None = None, years: int = FX_TREND_YEARS
) -> dict | None:
    """Latest close vs. its trailing `years`-year average, plus the window's range.

    Returns None when there is no data. "rolling_avg" is the trailing average as of each
    window day, NaN where the stored history is shorter than `years` before that day, so the
    chart never draws a partial-window average as if it were a full one.
    """
    if raw_df is None or raw_df.empty:
        return None
    df = raw_df[["Date", "Close"]].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.dropna().sort_values("Date").drop_duplicates(subset="Date", keep="last")
    if as_of is not None:
        df = df[df["Date"] <= pd.Timestamp(as_of)]
    if df.empty:
        return None

    latest_date = df["Date"].iloc[-1]
    latest_close = float(df["Close"].iloc[-1])
    window_start = latest_date - pd.DateOffset(years=years)
    window = df[df["Date"] > window_start]
    average = float(window["Close"].mean())

    series = df.set_index("Date")["Close"]
    rolling = series.rolling(f"{round(365.25 * years)}D").mean()
    full_history = series.index - pd.DateOffset(years=years) >= series.index[0]
    rolling = rolling.where(full_history)

    min_idx = window["Close"].idxmin()
    max_idx = window["Close"].idxmax()
    return {
        "years": years,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "latest_close": latest_close,
        "average": average,
        "diff": latest_close - average,
        "diff_pct": (latest_close / average - 1) * 100,
        "percentile": float((window["Close"] <= latest_close).mean() * 100),
        "min": float(window.loc[min_idx, "Close"]),
        "min_date": window.loc[min_idx, "Date"].strftime("%Y-%m-%d"),
        "max": float(window.loc[max_idx, "Close"]),
        "max_date": window.loc[max_idx, "Date"].strftime("%Y-%m-%d"),
        "window_start": window["Date"].iloc[0].strftime("%Y-%m-%d"),
        "observations": int(len(window)),
        "full_window": bool(window["Date"].iloc[0] - window_start <= pd.Timedelta(days=7)),
        "dates": window["Date"].dt.strftime("%Y-%m-%d").tolist(),
        "closes": window["Close"].astype(float).tolist(),
        "rolling_avg": [None if pd.isna(v) else float(v) for v in rolling.loc[window["Date"]]],
    }

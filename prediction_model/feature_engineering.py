"""Builds a richer per-ticker/per-date feature dataset for the prediction model —
see prediction_model_spec.md. Distinct from _signal_history.json, which only keeps the
compressed B/H/S/- action; this keeps the underlying ATR/Donchian numbers signal_engine
already computes but recommendation_engine.backfill_signal_history_deep discards.

Local/manual script, not part of the collect.yml/recommend.yml cron path — reuses
data_fetcher.fetch_ohlcv + signal_engine.compute_signals, no new signal logic.
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import data_fetcher
import signal_engine

OHLCV_CACHE_DIR = os.path.join(os.path.dirname(__file__), "ohlcv_cache")
FEATURE_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "feature_history.csv")
FETCH_START = "2007-01-01"  # matches recommendation_engine.backfill_signal_history_deep's default


def _cached_ohlcv(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """Local parquet cache so repeated runs don't re-hit yfinance for the same ticker —
    same reasoning as triple_barrier_backtest_spec.md's backtest_cache/."""
    os.makedirs(OHLCV_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(OHLCV_CACHE_DIR, f"{ticker}.parquet")
    if not force_refresh and os.path.exists(cache_path):
        return pd.read_parquet(cache_path)

    raw_df = data_fetcher.fetch_ohlcv(ticker, start=FETCH_START)
    time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)
    raw_df.to_parquet(cache_path, index=False)
    return raw_df


def _days_since(flags: pd.Series) -> pd.Series:
    """Per-row count of business days since `flags` was last True (0 on the True day itself).
    NaN before the first True in the series — there's no prior occurrence to measure from."""
    idx = pd.Series(range(len(flags)), index=flags.index)
    last_true_idx = idx.where(flags).ffill()
    return idx - last_true_idx


def build_ticker_features(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """One row per trading day for `ticker`: the mechanical action (same rules as
    signal_engine.get_mechanical_action) plus ATR-normalized numeric features that
    _signal_history.json's B/H/S/- compression throws away.
    """
    raw_df = _cached_ohlcv(ticker, force_refresh=force_refresh)
    if raw_df.empty:
        return pd.DataFrame()

    signals = signal_engine.compute_signals(raw_df)

    actions = [
        signal_engine.get_mechanical_action(
            {
                "breakout_20": bool(row.Breakout_20),
                "breakout_100": bool(row.Breakout_100),
                "exit_signal": bool(row.Exit_Signal),
            }
        )
        for row in signals.itertuples()
    ]

    return pd.DataFrame(
        {
            "date": signals["Date"].dt.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "action": actions,
            "close": signals["Close"],
            "atr": signals["ATR"],
            # Volatility-normalized daily return — comparable across low-ATR (TLT) and
            # high-ATR (BTC-USD) tickers, unlike a raw pct-change.
            "atr_norm_return": signals["Close"].diff() / signals["ATR"],
            # How far price sits above/below the 20-day Donchian upper band, in ATR units —
            # positive means already broken out, magnitude signals breakout strength.
            "dist_donchian20_atr": (signals["Close"] - signals["Donchian_Upper_20"]) / signals["ATR"],
            # Same idea for the trailing stop — how much cushion remains before an exit fires.
            "dist_trailing_stop_atr": (signals["Close"] - signals["Trailing_Stop"]) / signals["ATR"],
            # Signal "age" — how many days since a breakout/exit last fired, i.e. how stale
            # today's trend state is. NaN for rows before the first occurrence in this ticker's history.
            "days_since_breakout": _days_since(signals["Breakout_20"] | signals["Breakout_100"]),
            "days_since_exit": _days_since(signals["Exit_Signal"]),
        }
    )


def build_feature_history(tickers: dict | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """ASSET_CLASS_TICKERS by default. Writes FEATURE_HISTORY_PATH and returns the combined
    long-format DataFrame (one row per ticker/date)."""
    tickers = tickers if tickers is not None else data_fetcher.ASSET_CLASS_TICKERS
    frames = [build_ticker_features(ticker, force_refresh=force_refresh) for ticker in tickers]
    combined = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    combined.to_csv(FEATURE_HISTORY_PATH, index=False, encoding="utf-8-sig")
    return combined


if __name__ == "__main__":
    df = build_feature_history()
    print(f"Wrote {len(df)} rows ({df['ticker'].nunique()} tickers) to {FEATURE_HISTORY_PATH}")

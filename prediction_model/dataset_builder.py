"""Converts prediction_model/feature_history.csv (feature_engineering.py's output) into the
sliding-window (X, y) arrays for training -- the ATR-feature successor to sample_code.py's
one-hot-only version. See prediction_model_spec.md section 5 for the design.

Also produces a walk-forward train/val split instead of a random shuffle: consecutive
sliding-window samples share up to X_WINDOW + Y_WINDOW - 1 days, so a naive random split
would leak future information across the train/val boundary.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

FEATURE_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "feature_history.csv")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset.npz")

X_WINDOW = 30
Y_WINDOW = 30
VAL_FRACTION = 0.2
# Consecutive windows overlap by up to this many days -- any sample whose y-range would
# bleed across the train/val boundary is dropped from train (see walk_forward_split).
PURGE_GAP = X_WINDOW + Y_WINDOW - 1

# One-hot action order matches sample_code.py's original mapping.
ACTION_ORDER = ["H", "S", "B", "-"]
ACTION_SHORT = {"매수": "B", "HOLD": "H", "매도": "S"}
N_ACTION_FEATURES = len(ACTION_ORDER)

# Days-since-signal features are unbounded and NaN before a ticker's first breakout/exit --
# both get squashed into [0, 1] so they're on the same scale as the ATR-ratio features.
# Beyond DAYS_SINCE_CAP trading days, "how much staler" stops being informative, and "never
# happened yet" (NaN) is treated the same as "as stale as it gets" (1.0).
DAYS_SINCE_CAP = 252

FEATURE_NAMES = [
    "action_H", "action_S", "action_B", "action_unlisted",
    "atr_norm_return", "dist_donchian20_atr", "dist_trailing_stop_atr",
    "days_since_breakout_scaled", "days_since_exit_scaled",
]
N_FEATURES = len(FEATURE_NAMES)


def _scale_days_since(value: float) -> float:
    if pd.isna(value):
        return 1.0
    return min(value, DAYS_SINCE_CAP) / DAYS_SINCE_CAP


def load_wide_features(path: str = FEATURE_HISTORY_PATH) -> tuple[list[str], list[str], np.ndarray]:
    """Long-format feature_history.csv -> (dates, tickers, array) where
    array.shape == (len(dates), len(tickers), N_FEATURES).

    Dates a ticker doesn't have a row for (not yet listed, e.g. DBB/BTC-USD before their
    start dates) default to the "unlisted" one-hot slot + neutral numeric features --
    same union-of-dates handling as recommendation_engine's signal history tables.
    """
    df = pd.read_csv(path)
    df["action_short"] = df["action"].map(ACTION_SHORT)

    dates = sorted(df["date"].unique())
    tickers = sorted(df["ticker"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}
    ticker_idx = {t: i for i, t in enumerate(tickers)}

    array = np.zeros((len(dates), len(tickers), N_FEATURES), dtype=np.float32)
    array[:, :, ACTION_ORDER.index("-")] = 1.0  # default: unlisted

    for row in df.itertuples(index=False):
        d, t = date_idx[row.date], ticker_idx[row.ticker]
        action = row.action_short if row.action_short in ACTION_ORDER else "-"
        vec = np.zeros(N_FEATURES, dtype=np.float32)
        vec[ACTION_ORDER.index(action)] = 1.0
        vec[4] = 0.0 if pd.isna(row.atr_norm_return) else row.atr_norm_return
        vec[5] = 0.0 if pd.isna(row.dist_donchian20_atr) else row.dist_donchian20_atr
        vec[6] = 0.0 if pd.isna(row.dist_trailing_stop_atr) else row.dist_trailing_stop_atr
        vec[7] = _scale_days_since(row.days_since_breakout)
        vec[8] = _scale_days_since(row.days_since_exit)
        array[d, t] = vec

    return dates, tickers, array


def build_xy(array: np.ndarray, x_window: int = X_WINDOW, y_window: int = Y_WINDOW) -> tuple[np.ndarray, np.ndarray]:
    """X: (N, x_window, n_tickers, N_FEATURES) -- the raw feature window.
    y: (N, n_tickers) -- a smoothed log-ratio "trend score" for the following y_window
    days: log((buy_day_count + 1) / (sell_day_count + 1)), where buy/sell day counts come
    only from the 매수/매도 one-hot slots (HOLD and "unlisted" days are irrelevant to a
    ratio of the other two, unlike the earlier [매수, HOLD, 매도] proportion target this
    replaced -- see prediction_model_spec.md section 6 for why that target's three values
    didn't sum to 100% for weekday-only tickers).

    +1 (Laplace) smoothing avoids a division-by-zero when a 30-day window has zero buy or
    zero sell days, which is common -- 매수 (a fresh Donchian breakout) is a one-day
    punctuated event, while 매도 (closing below the trailing stop) is a state that can
    persist for many consecutive days during a drawdown, so 매도 day-counts are
    structurally larger than 매수 day-counts across nearly every one of these 12 tickers'
    full history (see prediction_model_spec.md section 6.1) -- a negative score is the
    structural norm, not evidence of a bearish read on its own; what matters is a ticker's
    score relative to its own historical average, not its distance from zero.
    """
    n_days = array.shape[0]
    buy_idx, sell_idx = ACTION_ORDER.index("B"), ACTION_ORDER.index("S")
    X_list, y_list = [], []
    for start in range(n_days - x_window - y_window + 1):
        X_list.append(array[start : start + x_window])
        y_window_slice = array[start + x_window : start + x_window + y_window, :, :N_ACTION_FEATURES]
        buy_days = y_window_slice[:, :, buy_idx].sum(axis=0)  # (n_tickers,)
        sell_days = y_window_slice[:, :, sell_idx].sum(axis=0)
        y_list.append(np.log((buy_days + 1) / (sell_days + 1)))
    return np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.float32)


def walk_forward_split(n_samples: int, val_fraction: float = VAL_FRACTION, purge: int = PURGE_GAP) -> tuple[np.ndarray, np.ndarray]:
    """Time-ordered split, not a random shuffle -- samples are drawn from overlapping
    sliding windows, so shuffling would let validation-period data leak into training.
    `purge` drops the last `purge` samples before the split point so no training sample's
    y-window extends into the validation period.
    """
    split_point = int(n_samples * (1 - val_fraction))
    train_idx = np.arange(0, max(split_point - purge, 0))
    val_idx = np.arange(split_point, n_samples)
    return train_idx, val_idx


def build_dataset(feature_history_path: str = FEATURE_HISTORY_PATH, save_path: str = DATASET_PATH):
    dates, tickers, array = load_wide_features(feature_history_path)
    X, y = build_xy(array)
    train_idx, val_idx = walk_forward_split(len(X))

    np.savez_compressed(
        save_path,
        X=X,
        y=y,
        train_idx=train_idx,
        val_idx=val_idx,
        tickers=np.array(tickers),
        feature_names=np.array(FEATURE_NAMES),
        dates=np.array(dates),
    )
    return X, y, train_idx, val_idx, tickers, dates


if __name__ == "__main__":
    X, y, train_idx, val_idx, tickers, dates = build_dataset()
    print(f"X shape: {X.shape}  (samples, {X_WINDOW}-day window, {len(tickers)} tickers, {N_FEATURES} features)")
    print(f"y shape: {y.shape}  (samples, {len(tickers)} tickers -- log((매수일+1)/(매도일+1)) trend score)")
    print(f"train samples: {len(train_idx)}, val samples: {len(val_idx)} (purge gap: {PURGE_GAP})")
    print(f"date range: {dates[0]} ~ {dates[-1]}")
    print(f"saved to: {DATASET_PATH}")

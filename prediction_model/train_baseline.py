"""Baseline model for prediction_model_spec.md step 3: one RandomForestRegressor per
ticker, trained on that ticker's own 30-day feature window (dataset_builder.py's X/y),
predicting the next-30-day [매수, HOLD, 매도] proportions.

Deliberately simple -- scikit-learn only (no new dependency), one single-asset model per
ticker rather than a cross-asset sequence model. See prediction_model_spec.md section 6:
the sliding-window samples overlap heavily (up to 59 days between adjacent samples), so
the effective independent sample count is much smaller than N=6212 -- a heavy model
(LSTM/Transformer) would be prone to overfitting before a simple baseline even sets a
performance floor to beat.
"""
from __future__ import annotations

import os
import sys

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset_builder import ACTION_ORDER, DATASET_PATH, build_dataset  # noqa: E402

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
RESULTS_PATH = os.path.join(MODEL_DIR, "baseline_results.csv")
UNLISTED_IDX = ACTION_ORDER.index("-")


def load_dataset(path: str = DATASET_PATH):
    if not os.path.exists(path):
        return build_dataset()
    d = np.load(path, allow_pickle=True)
    return d["X"], d["y"], d["train_idx"], d["val_idx"], d["tickers"].tolist(), d["dates"].tolist()


def _listed_samples(X: np.ndarray, sample_idx: np.ndarray, ticker_idx: int) -> np.ndarray:
    """Keep only samples where the ticker was actually listed as of the prediction date
    (last day of the X window) -- an all-"unlisted" window (e.g. BTC-USD before 2014-09-17)
    carries no real signal and would just teach the model "unlisted predicts unlisted",
    diluting the genuine training signal for the period the ticker actually traded.
    """
    last_day_unlisted = X[sample_idx, -1, ticker_idx, UNLISTED_IDX] == 1
    return sample_idx[~last_day_unlisted]


def train_ticker_model(X: np.ndarray, y: np.ndarray, train_idx: np.ndarray, val_idx: np.ndarray, ticker_idx: int):
    train_idx = _listed_samples(X, train_idx, ticker_idx)
    val_idx = _listed_samples(X, val_idx, ticker_idx)

    X_train = X[train_idx, :, ticker_idx, :].reshape(len(train_idx), -1)
    y_train = y[train_idx, ticker_idx, :]
    X_val = X[val_idx, :, ticker_idx, :].reshape(len(val_idx), -1)
    y_val = y[val_idx, ticker_idx, :]

    model = RandomForestRegressor(
        n_estimators=200, max_depth=8, min_samples_leaf=5, random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)
    pred = np.clip(model.predict(X_val), 0.0, 1.0)
    mae = mean_absolute_error(y_val, pred)

    # Naive baseline: always predict the train-set's average B/H/S proportion. A model
    # that can't beat this isn't learning anything from the 30-day window shape itself.
    baseline_pred = np.tile(y_train.mean(axis=0), (len(y_val), 1))
    baseline_mae = mean_absolute_error(y_val, baseline_pred)

    return model, mae, baseline_mae, len(train_idx), len(val_idx)


def train_all(save_models: bool = True) -> list[dict]:
    X, y, train_idx, val_idx, tickers, dates = load_dataset()
    os.makedirs(MODEL_DIR, exist_ok=True)

    results = []
    for i, ticker in enumerate(tickers):
        model, mae, baseline_mae, n_train, n_val = train_ticker_model(X, y, train_idx, val_idx, i)
        results.append(
            {
                "ticker": ticker,
                "mae": mae,
                "baseline_mae": baseline_mae,
                "improvement": baseline_mae - mae,
                "n_train": n_train,
                "n_val": n_val,
            }
        )
        if save_models:
            joblib.dump(model, os.path.join(MODEL_DIR, f"{ticker}_rf.joblib"))

    return results


if __name__ == "__main__":
    import csv

    results = sorted(train_all(), key=lambda r: -r["improvement"])

    print(f"{'Ticker':<10}{'MAE':>10}{'Baseline MAE':>15}{'Improvement':>13}{'n_train':>10}{'n_val':>8}")
    for r in results:
        print(
            f"{r['ticker']:<10}{r['mae']:>10.4f}{r['baseline_mae']:>15.4f}"
            f"{r['improvement']:>13.4f}{r['n_train']:>10}{r['n_val']:>8}"
        )

    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(RESULTS_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nsaved to: {RESULTS_PATH}")

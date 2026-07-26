"""Runs the trained baseline models (train_baseline.py) on the most recent 30-day window
to produce a "next 30 days" 매수/HOLD/매도 proportion prediction per ticker, packaged with
each model's own validation reliability (baseline_results.csv), and publishes the result
to Drive as _prediction_simulation.json for the daily report to read (report_builder.py's
_build_prediction_simulation_html, wired through recommendation_engine.py).

Manual/local script -- NOT part of collect.yml/recommend.yml (same principle as the rest
of prediction_model/, see prediction_model_spec.md section 7). Run this after retraining
(train_baseline.py) to refresh what the daily report shows; the cron only ever reads the
JSON this leaves in Drive, it never trains or predicts anything itself.
"""
from __future__ import annotations

import csv
import datetime
import os
import sys

import joblib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_builder import FEATURE_HISTORY_PATH, X_WINDOW, load_wide_features  # noqa: E402
from train_baseline import MODEL_DIR, RESULTS_PATH, UNLISTED_IDX  # noqa: E402

from drive_db import DriveDB  # noqa: E402

# Must stay in sync with recommendation_engine.PREDICTION_SIMULATION_FILENAME.
PREDICTION_SIMULATION_FILENAME = "_prediction_simulation.json"


def _load_reliability(path: str = RESULTS_PATH) -> dict[str, dict]:
    reliability = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            mae, baseline_mae = float(row["mae"]), float(row["baseline_mae"])
            reliability[row["ticker"]] = {
                "val_mae": round(mae, 4),
                "baseline_mae": round(baseline_mae, 4),
                "improvement_pct": round(100 * (baseline_mae - mae) / baseline_mae, 1),
            }
    return reliability


def _latest_window(array: np.ndarray, ticker_idx: int, x_window: int) -> tuple[np.ndarray | None, int | None]:
    """The x_window-day window ending on this ticker's own most recent listed day.

    The combined date axis's very last row is often a day only BTC-USD trades (it trades
    weekends; nothing else here does) -- using array[-x_window:] unconditionally would make
    every non-crypto ticker look "unlisted" on that day and get skipped entirely. Walk
    backward from the end to find each ticker's own last real trading day instead.
    """
    for end in range(array.shape[0] - 1, -1, -1):
        if array[end, ticker_idx, UNLISTED_IDX] == 0:
            start = end - x_window + 1
            if start < 0:
                return None, None
            return array[start : end + 1, ticker_idx, :], end
    return None, None


def generate_predictions(feature_history_path: str = FEATURE_HISTORY_PATH) -> dict:
    dates, tickers, array = load_wide_features(feature_history_path)
    reliability = _load_reliability()

    predictions = {}
    for i, ticker in enumerate(tickers):
        model_path = os.path.join(MODEL_DIR, f"{ticker}_rf.joblib")
        if not os.path.exists(model_path) or ticker not in reliability:
            continue

        window, end_idx = _latest_window(array, i, X_WINDOW)
        if window is None:
            continue

        model = joblib.load(model_path)
        buy, hold, sell = np.clip(model.predict(window.reshape(1, -1))[0], 0.0, 1.0)

        predictions[ticker] = {
            "as_of_date": dates[end_idx],
            "buy_pct": round(float(buy) * 100, 1),
            "hold_pct": round(float(hold) * 100, 1),
            "sell_pct": round(float(sell) * 100, 1),
            **reliability[ticker],
        }

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "predictions": predictions,
    }


def save_to_drive(result: dict) -> None:
    db = DriveDB()
    db.save_json(PREDICTION_SIMULATION_FILENAME, result)


if __name__ == "__main__":
    result = generate_predictions()
    for ticker, pred in result["predictions"].items():
        print(
            f"{ticker:<10} ({pred['as_of_date']})  B {pred['buy_pct']:>5.1f}%  "
            f"H {pred['hold_pct']:>5.1f}%  S {pred['sell_pct']:>5.1f}%  (개선율 {pred['improvement_pct']}%)"
        )
    save_to_drive(result)
    print(f"\nSaved to Drive as {PREDICTION_SIMULATION_FILENAME}")

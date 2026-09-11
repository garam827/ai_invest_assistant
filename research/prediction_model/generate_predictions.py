"""Run trained baseline models and save research predictions to Drive.

Manual research only: the daily pipeline and reports do not consume this output.
"""
from __future__ import annotations

import csv
import datetime
import os

import joblib
import numpy as np

from invest_assistant.storage.drive import DriveDB  # noqa: E402
from research.prediction_model.dataset_builder import (  # noqa: E402
    FEATURE_HISTORY_PATH,
    X_WINDOW,
    load_wide_features,
)
from research.prediction_model.train_baseline import (  # noqa: E402
    MODEL_DIR,
    RESULTS_PATH,
    UNLISTED_IDX,
)

# Independent research output; not loaded by the daily recommendation pipeline.
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
                "historical_avg_score": round(float(row["historical_avg_score"]), 3),
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
        trend_score = float(model.predict(window.reshape(1, -1))[0])

        predictions[ticker] = {
            "as_of_date": dates[end_idx],
            "trend_score": round(trend_score, 3),
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
            f"{ticker:<10} ({pred['as_of_date']})  추세점수 {pred['trend_score']:>+7.3f}  "
            f"(과거 평균 {pred['historical_avg_score']:>+7.3f}, 개선율 {pred['improvement_pct']}%)"
        )
    save_to_drive(result)
    print(f"\nSaved to Drive as {PREDICTION_SIMULATION_FILENAME}")

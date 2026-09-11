import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from invest_assistant.analysis import signals as signal_engine
from invest_assistant.data import market as data_fetcher
from invest_assistant.data.quality import validate_ohlcv
from invest_assistant.pipelines import collect as collection_pipeline
from invest_assistant.pipelines import recommend as recommendation_engine
from invest_assistant.storage.drive import DriveDB


def prices():
    return pd.DataFrame({
        "Date": pd.date_range("2026-03-01", periods=150),
        "Open": 100., "High": 102., "Low": 99., "Close": 101., "Volume": 1000,
    })


class DataQualityTests(unittest.TestCase):
    def test_nan_prices_cannot_become_hold(self):
        frame = prices()
        frame.loc[149, ["Open", "High", "Low", "Close"]] = np.nan
        with self.assertRaisesRegex(ValueError, "Invalid OHLCV"):
            signal_engine.get_latest_signal_summary(frame)

    def test_nonfinite_and_invalid_values(self):
        for column, value in [("Close", np.inf), ("High", 0), ("Volume", -1),
                              ("Date", pd.NaT)]:
            frame = prices()
            frame.loc[149, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                validate_ohlcv(frame)

    def test_valid_prices_keep_mechanical_hold(self):
        self.assertEqual(signal_engine.get_mechanical_action(
            signal_engine.get_latest_signal_summary(prices())), "HOLD")

    def test_invalid_update_does_not_overwrite_good_drive_data(self):
        db = object.__new__(DriveDB)
        db.load_ticker = Mock(return_value=prices())
        db._upload = Mock()
        incoming = prices().tail(1).copy()
        incoming["Close"] = np.nan
        with self.assertRaises(ValueError):
            db.upsert_ticker("SPY", incoming)
        db._upload.assert_not_called()

    def test_fetch_retries_invalid_adjusted_prices(self):
        good = prices().set_index("Date")
        bad = good.copy()
        bad.iloc[-1, bad.columns.get_loc("Close")] = np.nan
        with patch.object(data_fetcher.yf, "Ticker") as ticker, \
             patch.object(data_fetcher.time, "sleep"), self.assertLogs(data_fetcher.logger):
            ticker.return_value.history.side_effect = [bad, good]
            validate_ohlcv(data_fetcher.fetch_ohlcv("SPY"))
            self.assertEqual(ticker.return_value.history.call_count, 2)
            self.assertTrue(ticker.return_value.history.call_args.kwargs["auto_adjust"])

    def test_persistent_invalid_fetch_fails(self):
        bad = prices().set_index("Date")
        bad["Close"] = np.nan
        with patch.object(data_fetcher.yf, "Ticker") as ticker, \
             patch.object(data_fetcher.time, "sleep"), self.assertLogs(data_fetcher.logger):
            ticker.return_value.history.return_value = bad
            with self.assertRaises(ValueError):
                data_fetcher.fetch_ohlcv("SPY")
            self.assertEqual(ticker.return_value.history.call_count, 3)

    def test_incomplete_batch_cannot_publish(self):
        db = Mock()
        with patch.object(recommendation_engine, "get_recommendation_for_ticker", return_value=None), \
             self.assertLogs(recommendation_engine.logger):
            with self.assertRaisesRegex(RuntimeError, "refusing to publish"):
                recommendation_engine.run_asset_class_recommendations(db, tickers={"SPY": {}})
        db.save_json.assert_not_called()

    def test_collection_failure_blocks_downstream_workflow(self):
        with patch.object(collection_pipeline, "ASSET_CLASS_TICKERS", {"SPY": {}, "QQQ": {}}), \
             patch.object(collection_pipeline, "_update_one_ticker", side_effect=[ValueError("invalid"), None]) as update, \
             patch.object(collection_pipeline.time, "sleep"), self.assertLogs(collection_pipeline.logger):
            with self.assertRaisesRegex(RuntimeError, "SPY"):
                collection_pipeline.run_asset_class_update(Mock())
            self.assertEqual(update.call_count, 2)


if __name__ == "__main__":
    unittest.main()

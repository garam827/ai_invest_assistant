"""Display-only FX series: 3-year average comparison, collection boundaries, report section."""
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from invest_assistant import config
from invest_assistant.analysis.fx import compute_fx_trend
from invest_assistant.pipelines import collect
from invest_assistant.reporting import report


def fx_frame(start="2021-11-01", end="2026-11-06", base=1300.0):
    dates = pd.bdate_range(start, end)
    close = base + np.arange(len(dates)) * 0.1
    return pd.DataFrame({"Date": dates, "Open": close, "High": close + 5, "Low": close - 5,
                         "Close": close, "Volume": 0})


class FxTrendTests(unittest.TestCase):
    def test_average_uses_three_years_back_from_last_bar(self):
        df = fx_frame()
        trend = compute_fx_trend(df)
        window = df[df["Date"] > pd.Timestamp("2026-11-06") - pd.DateOffset(years=3)]
        self.assertEqual(trend["latest_date"], "2026-11-06")
        self.assertAlmostEqual(trend["average"], window["Close"].mean())
        self.assertAlmostEqual(trend["diff"], df["Close"].iloc[-1] - window["Close"].mean())
        self.assertEqual(trend["observations"], len(window))
        self.assertEqual(trend["percentile"], 100.0)  # monotonic series: latest is the max
        self.assertTrue(trend["full_window"])

    def test_as_of_truncates_before_windowing(self):
        df = fx_frame()
        trend = compute_fx_trend(df, as_of="2025-06-30")
        self.assertEqual(trend["latest_date"], "2025-06-30")
        self.assertLessEqual(max(trend["dates"]), "2025-06-30")

    def test_rolling_average_is_blank_without_full_history(self):
        trend = compute_fx_trend(fx_frame(start="2024-06-03"))
        self.assertFalse(trend["full_window"])
        self.assertTrue(all(v is None for v in trend["rolling_avg"]))
        full = compute_fx_trend(fx_frame())
        self.assertIsNone(full["rolling_avg"][0])
        self.assertIsNotNone(full["rolling_avg"][-1])

    def test_empty_input_returns_none(self):
        self.assertIsNone(compute_fx_trend(None))
        self.assertIsNone(compute_fx_trend(fx_frame(), as_of="2000-01-01"))


class FxCollectionTests(unittest.TestCase):
    def setUp(self):
        for name, value in [("COLLECTION_WORKERS", 1), ("COLLECTION_RETRY_ROUNDS", 0),
                            ("COLLECTION_RETRY_DELAY_SEC", 0), ("STREAMLIT_PUBLIC_MODE", False)]:
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fx_failure_is_reported_not_raised(self):
        with patch.object(collect, "_update_one_ticker", side_effect=ValueError("bad")), \
                self.assertLogs(collect.logger):
            result = collect.run_fx_update(Mock())
        self.assertEqual(result["failed"], ["KRW=X"])

    def test_universe_sync_ignores_fx_files(self):
        db = Mock()
        db.list_tickers.return_value = ["AAPL", "SPY", "KRW=X"]
        table = pd.DataFrame({"Symbol": ["AAPL"], "GICS Sector": ["IT"], "Security": ["Apple"],
                              "GICS Sub-Industry": ["Hardware"]})
        with patch.object(collect, "_fetch_sp500_table", return_value=table):
            result = collect.sync_universe(db)
        self.assertEqual(result["inactive"], [])

    def test_daily_fallback_excludes_fx(self):
        db = Mock()
        db.load_json.return_value = None
        db.list_tickers.return_value = ["AAPL", "KRW=X"]
        with patch.object(collect, "_run_updates", return_value={}) as run:
            collect.run_daily_update(db)
        self.assertEqual(run.call_args.args[1], ["AAPL"])

    def test_full_collection_runs_fx_after_assets(self):
        order = []
        with patch.object(collect, "sync_universe", return_value={}), \
                patch.object(collect, "run_daily_update", side_effect=lambda *a, **k: order.append("stocks")), \
                patch.object(collect, "run_asset_class_update", side_effect=lambda *a, **k: order.append("assets")), \
                patch.object(collect, "run_fx_update", side_effect=lambda *a, **k: order.append("fx")):
            collect.run_full_collection(Mock())
        self.assertEqual(order, ["stocks", "assets", "fx"])


class FxReportTests(unittest.TestCase):
    def test_report_and_markdown_include_fx_section(self):
        db = Mock()
        db.load_ticker.return_value = None
        trend = compute_fx_trend(fx_frame())
        results = {"SPY": {"date": "2026-11-06", "action": "HOLD", "close": 100}}
        html = report.build_daily_report_html(db, results, fx_trends={"KRW=X": trend})
        self.assertIn("환율 3년 평균 비교", html)
        self.assertIn(f"{trend['average']:,.2f}", html)
        self.assertEqual(html.count("cdn.plot.ly"), 1)
        markdown = report._build_report_markdown("2026-11-06", "", results, None, None,
                                                 fx_trends={"KRW=X": trend})
        self.assertIn("## 환율 3년 평균 비교", markdown)
        self.assertIn("원/달러 환율", markdown)

    def test_report_omits_fx_section_without_data(self):
        db = Mock()
        db.load_ticker.return_value = None
        html = report.build_daily_report_html(db, {"SPY": {"date": "2026-11-06", "action": "HOLD", "close": 100}})
        self.assertNotIn("환율 3년 평균 비교", html)


if __name__ == "__main__":
    unittest.main()

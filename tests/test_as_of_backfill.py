"""Historical as_of backfills must not leak data from after the day they represent."""
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from invest_assistant import config
from invest_assistant.pipelines import recommend
from invest_assistant.reporting import report


def _ohlcv(days: int = 260) -> pd.DataFrame:
    dates = pd.bdate_range("2025-10-01", periods=days)
    close = np.linspace(100, 150, days)
    return pd.DataFrame({
        "Date": dates, "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": np.full(days, 1_000_000),
    })


class AsOfBackfillTests(unittest.TestCase):
    def test_report_charts_are_truncated_at_as_of(self):
        df = _ohlcv()
        cutoff = df["Date"].iloc[200]
        db = Mock()
        db.load_ticker.return_value = df
        captured = []

        def fake_figure(ticker, view):
            captured.append(view)
            return Mock(to_html=Mock(return_value="<div>chart</div>"))

        results = {"SPY": {"date": cutoff.strftime("%Y-%m-%d"), "action": "HOLD", "close": 100}}
        with patch.object(report.chart_builder, "build_ticker_chart_figure", side_effect=fake_figure):
            report.build_daily_report_html(db, results, as_of=cutoff.strftime("%Y-%m-%d"))
        self.assertEqual(len(captured), 1)
        self.assertEqual(pd.to_datetime(captured[0]["Date"]).max(), cutoff)

    def _run(self, as_of):
        reco = {"ticker": "SPY", "date": "2026-09-09", "action": "HOLD", "close": 100}
        db = Mock()
        db.load_json.return_value = {}
        mocks = {}
        with ExitStack() as stack:
            for name, value in [("SKIP_LLM_AND_NEWS", False), ("IS_TEST_REPORT", False),
                                ("TELEGRAM_BOT_TOKEN", "token"), ("TELEGRAM_CHAT_ID", "chat")]:
                stack.enter_context(patch.object(config, name, value))
            stack.enter_context(patch.object(recommend, "get_recommendation_for_ticker", return_value=reco))
            stack.enter_context(patch.object(recommend, "get_sp500_signal_summary", return_value=[]))
            mocks["macro_issues"] = stack.enter_context(patch.object(recommend, "get_macro_issues_briefing", return_value=None))
            mocks["positions"] = stack.enter_context(patch.object(recommend.paper_trading, "load_positions", return_value=[]))
            mocks["snapshot"] = stack.enter_context(patch.object(recommend.data_fetcher, "fetch_macro_snapshot", return_value={}))
            mocks["overview"] = stack.enter_context(patch.object(recommend.llm_briefing, "generate_portfolio_overview", return_value="x"))
            mocks["build"] = stack.enter_context(patch.object(recommend.report_builder, "build_daily_report_html", return_value="r"))
            mocks["save"] = stack.enter_context(patch.object(recommend.report_store, "save_report"))
            mocks["telegram"] = stack.enter_context(patch.object(recommend.telegram_notifier, "notify_recommendations"))
            mocks["export"] = stack.enter_context(patch.object(recommend.static_export, "export_signals_json"))
            for name in ["export_universe_json", "export_chart_data", "export_reports_index"]:
                stack.enter_context(patch.object(recommend.static_export, name))
            recommend.run_asset_class_recommendations(db, {"SPY": {}}, as_of=as_of)
        return db, mocks

    def test_backfill_omits_present_only_sections(self):
        db, mocks = self._run("2026-09-09")
        for name in ["macro_issues", "positions", "snapshot", "overview", "telegram", "export"]:
            mocks[name].assert_not_called()
        kwargs = mocks["build"].call_args.kwargs
        self.assertEqual(kwargs["as_of"], "2026-09-09")
        self.assertEqual(kwargs["overview"], "")
        self.assertIsNone(kwargs["backtest_summary"])
        self.assertEqual(kwargs["paper_positions"], [])
        mocks["save"].assert_called_once()
        self.assertEqual(mocks["save"].call_args.args[1], "2026-09-09")
        self.assertNotIn("_backtest_summary.json", [c.args[0] for c in db.load_json.call_args_list])

    def test_daily_run_still_includes_present_sections(self):
        _, mocks = self._run(None)
        for name in ["macro_issues", "positions", "snapshot", "overview", "telegram", "export"]:
            mocks[name].assert_called_once()
        self.assertIsNone(mocks["build"].call_args.kwargs["as_of"])

    def test_cli_runs_each_as_of_date(self):
        with patch.object(recommend, "DriveDB") as drive, \
                patch.object(recommend, "run_asset_class_recommendations") as run:
            recommend.main(["--as-of", "2026-09-09", "--as-of", "2026-09-14"])
        self.assertEqual([c.kwargs["as_of"] for c in run.call_args_list], ["2026-09-09", "2026-09-14"])
        drive.assert_called_once()

    def test_cli_rejects_malformed_date_before_touching_drive(self):
        with patch.object(recommend, "DriveDB") as drive, self.assertRaises(ValueError):
            recommend.main(["--as-of", "2026/09/09"])
        drive.assert_not_called()


if __name__ == "__main__":
    unittest.main()

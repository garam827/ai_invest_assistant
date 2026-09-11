"""Exercise boundaries moved by the package/UI refactor without external services."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from invest_assistant import config
from invest_assistant.paths import PROJECT_ROOT
from invest_assistant.pipelines import recommend
from invest_assistant.publishing import static
from invest_assistant.reporting import report
from invest_assistant.storage import reports


class RefactorIntegrationTests(unittest.TestCase):
    def test_report_and_copy_summary_omit_individual_stock_signals(self):
        db = Mock()
        db.load_ticker.return_value = None
        results = {"SPY": {"date": "2026-09-08", "action": "HOLD", "close": 100}}
        html = report.build_daily_report_html(
            db, results, overview="Shared <overview>",
            sp500_signals=[{"ticker": "UNIQUE_STOCK", "action": "매수", "close": 50}],
        )
        self.assertIn("Shared &lt;overview&gt;", html)
        self.assertIn("SPY", html)
        self.assertNotIn("UNIQUE_STOCK", html)
        self.assertNotIn("S&amp;P 500 매수/매도 시그널", html)

    def test_static_export_and_report_storage_use_injected_output_directories(self):
        results = {"SPY": {"date": "2026-09-08", "action": "HOLD", "close": 100}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config, "IS_TEST_REPORT", False), \
                patch.object(static, "DOCS_DATA_DIR", tmp), \
                patch.object(reports, "LOCAL_REPORT_DIR", tmp):
            static.export_signals_json(results, [], overview="Shared overview")
            payload = json.loads((Path(tmp) / "signals_asset_class.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["overview"], "Shared overview")
            self.assertEqual(payload["tickers"][0]["action"], "HOLD")
            db = Mock()
            reports.save_report(db, "2026-09-08_test", "<html>test</html>")
            self.assertEqual((Path(tmp) / "2026-09-08_test.html").read_text(encoding="utf-8"), "<html>test</html>")
            db.save_text.assert_called_once_with("_report_2026-09-08_test.html", "<html>test</html>")

    def test_daily_pipeline_reuses_one_overview_for_both_outputs(self):
        from contextlib import ExitStack
        results = {"ticker": "SPY", "date": "2026-09-08", "action": "HOLD", "close": 100}
        db = Mock()
        db.load_json.return_value = {}
        with ExitStack() as stack:
            for name, value in [("SKIP_LLM_AND_NEWS", False), ("IS_TEST_REPORT", False),
                                ("TELEGRAM_BOT_TOKEN", ""), ("TELEGRAM_CHAT_ID", "")]:
                stack.enter_context(patch.object(config, name, value))
            stack.enter_context(patch.object(recommend, "get_recommendation_for_ticker", return_value=results))
            stack.enter_context(patch.object(recommend, "get_sp500_signal_summary", return_value=[]))
            stack.enter_context(patch.object(recommend, "get_macro_issues_briefing", return_value=None))
            stack.enter_context(patch.object(recommend.paper_trading, "load_positions", return_value=[]))
            stack.enter_context(patch.object(recommend.data_fetcher, "fetch_macro_snapshot", return_value={}))
            overview = stack.enter_context(patch.object(recommend.llm_briefing, "generate_portfolio_overview", return_value="Once"))
            build = stack.enter_context(patch.object(recommend.report_builder, "build_daily_report_html", return_value="report"))
            stack.enter_context(patch.object(recommend.report_store, "save_report"))
            export = stack.enter_context(patch.object(recommend.static_export, "export_signals_json"))
            for name in ["export_universe_json", "export_chart_data", "export_reports_index"]:
                stack.enter_context(patch.object(recommend.static_export, name))
            recommend.run_asset_class_recommendations(db, {"SPY": {}})
            overview.assert_called_once()
            self.assertEqual(build.call_args.kwargs["overview"], "Once")
            self.assertEqual(export.call_args.kwargs["overview"], "Once")

    def test_streamlit_six_tabs_and_stock_selection_render_without_network(self):
        db = Mock()
        db.load_json.return_value = {}
        db.list_filenames.return_value = []
        db.list_tickers.return_value = ["AAPL"]
        db.load_ticker.return_value = pd.DataFrame({
            "Date": pd.date_range("2026-03-01", periods=150),
            "Open": 100., "High": 102., "Low": 99., "Close": 101., "Volume": 1000,
        })
        st.cache_data.clear()
        st.cache_resource.clear()
        with patch("apps.streamlit.services.DriveDB", return_value=db):
            app = AppTest.from_file(str(PROJECT_ROOT / "apps/streamlit/app.py"), default_timeout=20).run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertEqual(len(app.tabs), 6)
            app.radio(key="paper_ticker_group").set_value("S&P 500 개별종목").run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            db.save_json.assert_not_called()
        st.cache_data.clear()
        st.cache_resource.clear()


if __name__ == "__main__":
    unittest.main()

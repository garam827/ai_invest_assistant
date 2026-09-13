"""Deployment boundaries: offline public UI, OAuth persistence and concurrency."""
from __future__ import annotations

import copy
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import streamlit as st
from google.auth.exceptions import RefreshError
from streamlit.testing.v1 import AppTest

from invest_assistant import config, deployment, universe
from invest_assistant.analysis import signals
from invest_assistant.data import news
from invest_assistant.paths import PROJECT_ROOT
from invest_assistant.portfolio import paper
from invest_assistant.recommendations import briefing
from invest_assistant.storage import drive, runtime
from invest_assistant.storage.snapshot import SnapshotDB


def write_snapshot(root: Path) -> SnapshotDB:
    (root / "data/charts").mkdir(parents=True)
    (root / "reports").mkdir()
    instruments = [{"ticker": t, **m} for t, m in universe.ASSET_CLASS_TICKERS.items()]
    payloads = {
        "universe": {"asset_classes": instruments, "sp500": [{"ticker": "AAPL", "sector": "Technology"}]},
        "signals_asset_class": {"generated_at": "2026-09-12T00:00:00Z", "tickers": [
            {"ticker": "SPY", "date": "2026-09-11", "action": "HOLD", "close": 101,
             "text": "Saved analysis", "news": []}]},
        "reports": {"dates": [{"date": "2026-09-11", "actions": {"SPY": "HOLD"}}]},
    }
    for name, data in payloads.items():
        (root / f"data/{name}.json").write_text(json.dumps(data), encoding="utf-8")
    frame = pd.DataFrame({"Date": pd.date_range("2026-03-01", periods=160),
                          "Open": 100., "High": 102., "Low": 99., "Close": 101., "Volume": 1000})
    chart = signals.compute_signals(frame).to_json(orient="records", date_format="iso")
    for ticker in [*universe.ASSET_CLASS_TICKERS, "AAPL"]:
        (root / f"data/charts/{ticker}.json").write_text(chart, encoding="utf-8")
    (root / "reports/2026-09-11.html").write_text("<html>Public report</html>", encoding="utf-8")
    return SnapshotDB(root)


class PublicDeploymentTests(unittest.TestCase):
    def test_public_ui_browses_charts_and_reports_without_external_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            db = write_snapshot(Path(directory))
            st.cache_data.clear()
            st.cache_resource.clear()
            with patch.object(config, "STREAMLIT_PUBLIC_MODE", True), \
                    patch("apps.streamlit.services.SnapshotDB", return_value=db), \
                    patch("apps.streamlit.services.DriveDB", side_effect=AssertionError("Drive forbidden")), \
                    patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")), \
                    patch.object(briefing, "_call_chat") as llm, \
                    patch.object(news, "fetch_ticker_news_exa") as exa:
                app = AppTest.from_file(str(PROJECT_ROOT / "apps/streamlit/app.py"), default_timeout=20).run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertEqual(len(app.tabs), 4)
                self.assertNotIn("데이터 적재", [t.label for t in app.tabs])
                self.assertNotIn("모의 투자", [t.label for t in app.tabs])
                app.selectbox(key="asset_category_select").set_value("주식").run()
                app.button(key="FormSubmitter:asset_controls-조회").click().run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertTrue(app.get("plotly_chart"))
                self.assertFalse(any("뉴스/분석" in b.label for b in app.button))
                app.button(key="FormSubmitter:sp500_controls-조회").click().run()
                self.assertFalse(app.exception, str(app.exception))
                app.button(key="FormSubmitter:report_download_form-준비").click().run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertTrue(app.get("download_button"))
                llm.assert_not_called()
                exa.assert_not_called()
            st.cache_data.clear()
            st.cache_resource.clear()

    def test_public_mode_blocks_backend_writes_and_paid_apis(self):
        with patch.object(config, "STREAMLIT_PUBLIC_MODE", True), patch("requests.post") as post:
            operations = [
                lambda: drive.DriveDB(),
                lambda: briefing._call_chat("system", "user"),
                lambda: news.fetch_ticker_news_exa("SPY"),
                lambda: paper.open_position(Mock(), "SPY", "2026-09-11", 1, 100),
                lambda: paper.close_position(Mock(), "position"),
                lambda: paper.save_positions(Mock(), []),
            ]
            for operation in operations:
                with self.assertRaises(PermissionError):
                    operation()
            post.assert_not_called()

    def test_missing_snapshot_fails_preflight(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "STREAMLIT_PUBLIC_MODE", True), \
                patch.object(deployment, "SnapshotDB", return_value=SnapshotDB(Path(directory))):
            with self.assertRaisesRegex(RuntimeError, "Public data is missing"):
                deployment.preflight()

    def test_snapshot_does_not_expose_arbitrary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            db = write_snapshot(Path(directory))
            db.validate()
            self.assertIsNone(db.load_json("token.json"))
            self.assertIsNone(db.load_text("../../token.json"))
            with self.assertRaises(ValueError):
                db.load_ticker("../../token")
            self.assertIsNone(db.load_json("_paper_trades.json"))
            self.assertEqual(db.load_text("_report_2026-09-11.html"), "<html>Public report</html>")


class CredentialTests(unittest.TestCase):
    def test_refresh_is_saved_atomically_and_survives_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oauth/token.json"
            runtime.atomic_write_private(str(path), '{"old":true}')
            creds = Mock(valid=False, expired=True, refresh_token="test-only")
            creds.to_json.return_value = '{"new":true}'
            with patch.object(config, "GOOGLE_OAUTH_TOKEN_PATH", str(path)), \
                    patch.object(config, "STREAMLIT_PUBLIC_MODE", False), \
                    patch.object(drive.Credentials, "from_authorized_user_file", return_value=creds), \
                    patch.object(drive, "InstalledAppFlow") as flow:
                drive._load_credentials()
                self.assertEqual(json.loads(path.read_text()), {"new": True})
                creds.valid = True
                drive._load_credentials()
                creds.refresh.assert_called_once()
                flow.from_client_secrets_file.assert_not_called()
            self.assertEqual([p.name for p in path.parent.iterdir()], ["token.json"])

    def test_missing_token_in_headless_mode_never_opens_a_browser(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "GOOGLE_OAUTH_TOKEN_PATH", str(Path(directory) / "token.json")), \
                patch.object(config, "STREAMLIT_PUBLIC_MODE", False), \
                patch.object(config, "GOOGLE_OAUTH_ALLOW_INTERACTIVE", False), \
                patch.object(drive, "InstalledAppFlow") as flow:
            with self.assertRaisesRegex(RuntimeError, "locally first"):
                drive._load_credentials()
            flow.from_client_secrets_file.assert_not_called()

    def test_failed_replace_preserves_previous_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            path.write_text("previous", encoding="utf-8")
            with patch.object(runtime.os, "replace", side_effect=PermissionError("read-only")):
                with self.assertRaises(PermissionError):
                    runtime.atomic_write_private(str(path), "new")
            self.assertEqual(path.read_text(), "previous")
            self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_revoked_token_reports_reauthorization_without_secret_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            path.write_text("{}")
            creds = Mock(valid=False, expired=True, refresh_token="test-only")
            creds.refresh.side_effect = RefreshError("provider-specific details")
            with patch.object(config, "GOOGLE_OAUTH_TOKEN_PATH", str(path)), \
                    patch.object(drive.Credentials, "from_authorized_user_file", return_value=creds):
                with self.assertRaisesRegex(RuntimeError, "renewed on a trusted local machine"):
                    drive._load_credentials()
            self.assertEqual(path.read_text(), "{}")


class ConcurrencyTests(unittest.TestCase):
    def test_two_position_writers_keep_both_updates(self):
        data = {"positions": []}
        class DB:
            def load_json(self, name):
                result = copy.deepcopy(data)
                time.sleep(0.02)
                return result
            def save_json(self, name, value):
                data.update(copy.deepcopy(value))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda ticker: paper.open_position(DB(), ticker, "2026-09-11", 1, 100), ["SPY", "QQQ"]))
        self.assertEqual({p["ticker"] for p in data["positions"]}, {"SPY", "QQQ"})

    def test_shared_drive_transport_is_not_entered_concurrently(self):
        db = object.__new__(drive.DriveDB)
        db.folder_id = "test-folder"
        active = 0
        peak = 0
        guard = threading.Lock()
        def execute():
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return {"files": [{"name": "SPY.parquet"}]}
        db.service = Mock()
        db.service.files.return_value.list.return_value.execute.side_effect = execute
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: db.list_tickers(), range(2)))
        self.assertEqual(results, [["SPY"], ["SPY"]])
        self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()

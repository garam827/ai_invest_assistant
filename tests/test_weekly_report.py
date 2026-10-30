"""Weekly report: calendar/window math, stats, stored-signal grid, special-briefing
accumulation, publication gating, index format, and HTML escaping. All offline."""
import datetime
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from invest_assistant import config
from invest_assistant import universe
from invest_assistant.analysis import signals as signal_engine
from invest_assistant.analysis import weekly as weekly_calc
from invest_assistant.pipelines import recommend
from invest_assistant.pipelines import weekly as weekly_pipeline
from invest_assistant.publishing import static as static_export
from invest_assistant.publishing import telegram
from invest_assistant.recommendations import briefing
from invest_assistant.recommendations import engine
from invest_assistant.recommendations import weekly as weekly_briefing
from invest_assistant.reporting import weekly as weekly_report
from invest_assistant.storage import reports as report_store

D = datetime.date
TICKERS = list(universe.ASSET_CLASS_TICKERS)
CRYPTO = ("BTC-USD", "ETH-USD")
W44_DAYS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def _ohlcv(dates, start=100.0, end=150.0) -> pd.DataFrame:
    close = np.linspace(start, end, len(dates))
    return pd.DataFrame({
        "Date": pd.to_datetime(dates), "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": np.full(len(dates), 1_000_000),
    })


def _frames(last="2026-10-30"):
    weekdays = pd.bdate_range("2026-01-02", last)
    everyday = pd.date_range("2026-01-02", last)
    return {t: _ohlcv(everyday if t in CRYPTO else weekdays) for t in TICKERS}


def _history(days=W44_DAYS):
    history = {d: {t: "HOLD" for t in TICKERS} for d in days}
    history["2026-10-28"]["QQQ"] = "매수"
    return history


class CalendarTests(unittest.TestCase):
    def test_week_id_and_bounds(self):
        self.assertEqual(weekly_calc.week_id(D(2026, 10, 30)), "2026-W44")
        self.assertEqual(weekly_calc.parse_week("2026-W44"), (D(2026, 10, 26), D(2026, 11, 1)))
        self.assertEqual(len(weekly_calc.expected_trading_days("2026-W44")), 5)

    def test_iso_year_boundaries(self):
        self.assertEqual(weekly_calc.week_id(D(2025, 12, 29)), "2026-W01")
        self.assertEqual(weekly_calc.week_id(D(2027, 1, 1)), "2026-W53")
        self.assertEqual(
            weekly_calc.expected_trading_days("2026-W53"),
            [D(2026, 12, 28), D(2026, 12, 29), D(2026, 12, 30), D(2026, 12, 31)],
        )
        # New Year's Day on Saturday is not observed on the Friday before.
        self.assertTrue(weekly_calc.is_trading_day(D(2021, 12, 31)))

    def test_holiday_weeks(self):
        self.assertNotIn(D(2026, 11, 26), weekly_calc.expected_trading_days("2026-W48"))  # Thanksgiving
        self.assertEqual(len(weekly_calc.expected_trading_days("2026-W48")), 4)
        self.assertFalse(weekly_calc.is_trading_day(D(2026, 4, 3)))  # Good Friday
        self.assertFalse(weekly_calc.is_trading_day(D(2026, 7, 3)))  # July 4 observed
        self.assertFalse(weekly_calc.is_trading_day(D(2026, 6, 19)))  # Juneteenth

    def test_invalid_week_rejected(self):
        for bad in ("2026-44", "2026-W54", "W44", "2025-W53"):
            with self.assertRaises(ValueError):
                weekly_calc.parse_week(bad)

    def test_default_target_week_is_latest_completed(self):
        self.assertEqual(weekly_calc.default_target_week(D(2026, 10, 30)), "2026-W43")  # Fri
        self.assertEqual(weekly_calc.default_target_week(D(2026, 10, 31)), "2026-W44")  # Sat
        self.assertEqual(weekly_calc.default_target_week(D(2026, 11, 1)), "2026-W44")  # Sun
        self.assertEqual(weekly_calc.default_target_week(D(2026, 11, 2)), "2026-W44")  # Mon


class WindowAndFreshnessTests(unittest.TestCase):
    def test_short_week_window_and_period(self):
        dates = [d for d in pd.bdate_range("2026-10-01", "2026-11-27") if d != pd.Timestamp("2026-11-26")]
        window = weekly_calc.resolve_week_window("2026-W48", _ohlcv(dates))
        self.assertEqual(window.trading_days, ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27"])
        self.assertEqual(window.period, "11/23~11/27")
        self.assertEqual(window.prev_close_date, "2026-11-20")

    def test_prev_close_crosses_year_end(self):
        dates = [d for d in pd.bdate_range("2026-12-01", "2027-01-08") if d != pd.Timestamp("2027-01-01")]
        window = weekly_calc.resolve_week_window("2027-W01", _ohlcv(dates))
        self.assertEqual(window.prev_close_date, "2026-12-31")
        self.assertEqual(window.trading_days[0], "2027-01-04")

    def test_week_without_bars_fails(self):
        with self.assertRaises(RuntimeError):
            weekly_calc.resolve_week_window("2026-W45", _frames()["SPY"])

    def test_missing_final_bar_fails_before_publication(self):
        frames = _frames()
        frames["GLD"] = frames["GLD"][frames["GLD"]["Date"] < "2026-10-30"]
        window = weekly_calc.resolve_week_window("2026-W44", frames["SPY"])
        with self.assertRaisesRegex(RuntimeError, "GLD"):
            weekly_calc.check_freshness(window, frames, _history(), strict=False)

    def test_strict_requires_signal_history_and_calendar(self):
        frames = _frames()
        window = weekly_calc.resolve_week_window("2026-W44", frames["SPY"])
        self.assertEqual(weekly_calc.check_freshness(window, frames, _history(), strict=True), [])
        with self.assertRaisesRegex(RuntimeError, "signal history"):
            weekly_calc.check_freshness(window, frames, _history(W44_DAYS[:-1]), strict=True)
        warnings = weekly_calc.check_freshness(window, frames, _history(W44_DAYS[:-1]), strict=False)
        self.assertEqual(len(warnings), 1)

    def test_holiday_friday_passes_strict(self):
        last = "2026-04-02"  # Good Friday 2026-04-03 closed
        frames = {t: _ohlcv(pd.bdate_range("2026-01-02", last)) for t in TICKERS}
        window = weekly_calc.resolve_week_window("2026-W14", frames["SPY"])
        history = {last: {t: "HOLD" for t in TICKERS}}
        self.assertEqual(weekly_calc.check_freshness(window, frames, history, strict=True), [])


class WeeklyStatsTests(unittest.TestCase):
    def test_return_high_low_and_distances(self):
        frames = _frames()
        window = weekly_calc.resolve_week_window("2026-W44", frames["SPY"])
        df = frames["SPY"]
        stats = weekly_calc.compute_asset_week(df, window)
        closes = df.set_index(df["Date"].dt.strftime("%Y-%m-%d"))["Close"]
        self.assertAlmostEqual(stats["return_pct"], (closes["2026-10-30"] / closes["2026-10-23"] - 1) * 100)
        self.assertAlmostEqual(stats["high"], closes["2026-10-30"] + 1)
        self.assertAlmostEqual(stats["low"], closes["2026-10-26"] - 1)
        latest = signal_engine.compute_signals(df).iloc[-1]
        close = closes["2026-10-30"]
        self.assertAlmostEqual(stats["stop_distance_pct"], (close - latest["Trailing_Stop"]) / close * 100)
        self.assertAlmostEqual(stats["dc20_distance_pct"], (latest["Donchian_Upper_20"] / close - 1) * 100)

    def test_crypto_uses_us_trading_days_only(self):
        frames = _frames()
        df = frames["BTC-USD"].copy()
        df.loc[df["Date"] == "2026-10-31", "High"] = 10_000  # weekend spike after the week
        df.loc[df["Date"] == "2026-10-25", "Low"] = 1  # Sunday before the week
        window = weekly_calc.resolve_week_window("2026-W44", frames["SPY"])
        stats = weekly_calc.compute_asset_week(df, window)
        self.assertLess(stats["high"], 10_000)
        self.assertGreater(stats["low"], 1)
        friday = df.set_index(df["Date"].dt.strftime("%Y-%m-%d"))["Close"]
        self.assertAlmostEqual(stats["prev_close"], friday["2026-10-23"])

    def test_signal_changes_are_transitions_of_stored_records(self):
        window = weekly_calc.resolve_week_window("2026-W44", _frames()["SPY"])
        history = _history()
        for day in W44_DAYS:
            history[day]["GLD"] = "매도"  # below its stop all week: a state, not a change
        history["2026-10-30"]["TLT"] = "매도"
        del history["2026-10-27"]["SPY"]
        prev = {t: "HOLD" for t in TICKERS}
        prev["GLD"] = "매도"
        prev["UNG"] = "매도"
        with patch.object(signal_engine, "get_mechanical_action") as mechanical:
            grid = weekly_calc.week_signal_grid(history, window, TICKERS)
            changes = weekly_calc.signal_changes(grid, prev)
        mechanical.assert_not_called()
        self.assertIsNone(grid["2026-10-27"]["SPY"])
        self.assertEqual(changes, {
            "UNG": [("2026-10-26", "매도", "HOLD")],
            "QQQ": [("2026-10-28", "HOLD", "매수"), ("2026-10-29", "매수", "HOLD")],
            "TLT": [("2026-10-30", "HOLD", "매도")],
        })

    def test_rule_based_regime(self):
        stats = {t: {"return_pct": 1.0 if t in weekly_calc.RISK_TICKERS else -0.5} for t in TICKERS}
        self.assertEqual(weekly_calc.rule_based_regime(stats)[0], "위험선호")
        stats = {t: {"return_pct": -1.0 if t in weekly_calc.RISK_TICKERS else 0.5} for t in TICKERS}
        self.assertEqual(weekly_calc.rule_based_regime(stats)[0], "위험회피")
        stats = {t: {"return_pct": 1.0} for t in TICKERS}
        self.assertEqual(weekly_calc.rule_based_regime(stats)[0], "혼조")


class SpecialBriefingRecordTests(unittest.TestCase):
    def test_accumulates_and_trims(self):
        db = Mock()
        db.load_json.return_value = {"2026-01-02": {"crypto": {"text": "old"}}, "2026-10-26": {"crypto": {"text": "a"}}}
        section = {"text": "t", "news": [{"title": "n"}]}
        self.assertTrue(engine.record_special_briefings(db, "2026-10-27", {"crypto": section, "basel3": None, "macro": section}))
        name, saved = db.save_json.call_args.args
        self.assertEqual(name, engine.SPECIAL_BRIEFINGS_FILENAME)
        self.assertEqual(sorted(saved), ["2026-10-26", "2026-10-27"])
        self.assertEqual(sorted(saved["2026-10-27"]), ["crypto", "macro"])

    def test_nothing_written_when_all_sections_skipped(self):
        db = Mock()
        self.assertFalse(engine.record_special_briefings(db, "2026-10-27", {"crypto": None, "basel3": None}))
        db.save_json.assert_not_called()

    def _run_recommend(self, as_of=None, is_test=False):
        reco = {"ticker": "SPY", "date": "2026-10-27", "action": "HOLD", "close": 100}
        section = {"text": "digest", "news": []}
        db = Mock()
        db.load_json.return_value = {}
        with ExitStack() as stack:
            for name, value in [("SKIP_LLM_AND_NEWS", False), ("IS_TEST_REPORT", is_test),
                                ("TELEGRAM_BOT_TOKEN", ""), ("TELEGRAM_CHAT_ID", "")]:
                stack.enter_context(patch.object(config, name, value))
            stack.enter_context(patch.object(recommend, "get_recommendation_for_ticker", return_value=reco))
            stack.enter_context(patch.object(recommend, "get_sp500_signal_summary", return_value=[]))
            for name in ["get_macro_issues_briefing", "get_crypto_special_briefing", "get_basel3_special_briefing"]:
                stack.enter_context(patch.object(recommend, name, return_value=section))
            stack.enter_context(patch.object(recommend.paper_trading, "load_positions", return_value=[]))
            stack.enter_context(patch.object(recommend.paper_trading, "compute_position_returns", return_value=[]))
            stack.enter_context(patch.object(recommend.data_fetcher, "fetch_macro_snapshot", return_value={}))
            stack.enter_context(patch.object(recommend.llm_briefing, "generate_portfolio_overview", return_value="x"))
            stack.enter_context(patch.object(recommend.report_builder, "build_daily_report_html", return_value="r"))
            stack.enter_context(patch.object(recommend.report_store, "save_report"))
            for name in ["export_signals_json", "export_universe_json", "export_chart_data", "export_reports_index"]:
                stack.enter_context(patch.object(recommend.static_export, name))
            record = stack.enter_context(patch.object(recommend, "record_special_briefings"))
            recommend.run_asset_class_recommendations(db, {"SPY": {}}, as_of=as_of)
        return record

    def test_recommend_records_real_runs_only(self):
        record = self._run_recommend()
        record.assert_called_once()
        self.assertEqual(record.call_args.args[1], "2026-10-27")
        self.assertEqual(sorted(record.call_args.args[2]), ["basel3", "crypto", "macro"])
        self._run_recommend(as_of="2026-10-27").assert_not_called()
        self._run_recommend(is_test=True).assert_not_called()


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        frames = _frames()
        self.window = weekly_calc.resolve_week_window("2026-W44", frames["SPY"])
        self.stats = {t: weekly_calc.compute_asset_week(frames[t], self.window) for t in TICKERS}
        self.grid = weekly_calc.week_signal_grid(_history(), self.window, TICKERS)
        self.changes = weekly_calc.signal_changes(self.grid)

    def test_llm_failure_falls_back_to_rules(self):
        with patch.object(config, "SKIP_LLM_AND_NEWS", False), \
                patch.object(briefing, "_call_chat", side_effect=RuntimeError("down")):
            result, source = weekly_briefing.get_weekly_asset_briefing(self.window, self.stats, self.grid, self.changes, {})
        self.assertEqual(source, "rule")
        self.assertIn(result["국면"], weekly_calc.REGIMES)
        self.assertIn("QQQ HOLD→매수(10/28)", result["근거"])
        self.assertEqual(set(weekly_briefing.CATEGORIES) - set(result), set())

    def test_llm_reply_is_parsed_and_invalid_regime_replaced(self):
        reply = "요약: 조용한 한 주\n국면: 강세장\n근거: 이유\n주식: 주식 해설\n이어지는 줄"
        with patch.object(config, "SKIP_LLM_AND_NEWS", False), \
                patch.object(briefing, "_call_chat", return_value=reply):
            result, source = weekly_briefing.get_weekly_asset_briefing(self.window, self.stats, self.grid, self.changes, {})
        self.assertEqual(source, "llm")
        self.assertEqual(result["요약"], "조용한 한 주")
        self.assertIn(result["국면"], weekly_calc.REGIMES)
        self.assertEqual(result["주식"], "주식 해설\n이어지는 줄")
        self.assertTrue(result["채권"])  # filled from the rule-based text

    def test_skip_uses_rules_without_llm(self):
        with patch.object(config, "SKIP_LLM_AND_NEWS", True), patch.object(briefing, "_call_chat") as chat:
            _, source = weekly_briefing.get_weekly_asset_briefing(self.window, self.stats, self.grid, self.changes, {})
            text, checkpoint_source = weekly_briefing.get_weekly_checkpoints({"2026-10-26": {"text": "FOMC 11/4", "news": []}})
        chat.assert_not_called()
        self.assertEqual((source, checkpoint_source), ("rule", "rule"))
        self.assertIn("FOMC 11/4", text)

    def test_number_rows_must_appear_in_articles(self):
        corpus = "BitMine holds 3,500,000 ETH; onchain RWA value reached $24.1 billion"
        text = "1. BMNR ETH 보유량 | 3,500,000 ETH | 10/27 | BitMine\n- RWA 총액 | 249억 달러 | 10/28 | x\n- 솔라나 RWA | 7.5억 | 10/29 | y\n깨진 행"
        rows, dropped = weekly_briefing.verify_number_rows(text, corpus)
        self.assertEqual([r["metric"] for r in rows], ["BMNR ETH 보유량"])
        self.assertEqual(dropped, 3)

    def test_rule_based_theme_flows(self):
        def item(title):
            return {"title": title, "link": f"https://{title}"}
        daily = {
            "2026-10-26": {"text": "", "news": [item("old"), item("kept")]},
            "2026-10-30": {"text": "", "news": [item("kept"), item("fresh")]},
        }
        flows = weekly_briefing.rule_based_theme(daily, [item("search")], ("ETH-USD",), self.stats, self.grid)
        self.assertIn("kept", flows["반복"])
        self.assertIn("fresh", flows["신규"])
        self.assertIn("search", flows["신규"])
        self.assertIn("old", flows["소멸"])

    def test_bracket_parser(self):
        parsed = briefing._parse_bracket_sections("서론\n[반복]\n1. a\n[수치] 없음\n[다음주]\n- b", briefing.WEEKLY_SPECIAL_THEME_KEYS)
        self.assertEqual(parsed, {"반복": "1. a", "수치": "없음", "다음주": "- b"})


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.reports_dir = os.path.join(root, "reports")
        self.weekly_dir = os.path.join(self.reports_dir, "weekly")
        self.data_dir = os.path.join(root, "data")
        os.makedirs(self.reports_dir)
        for day in W44_DAYS[:3]:
            open(os.path.join(self.reports_dir, f"{day}.html"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, week=None, skip=False, test=False, llm_reply="요약: <script>alert(1)</script>\n국면: 혼조\n근거: r"):
        frames = _frames()
        stored = {
            engine.SIGNAL_HISTORY_FILENAME: {**_history(), "2026-11-02": {t: "매도" for t in TICKERS}},
            engine.SPECIAL_BRIEFINGS_FILENAME: {
                "2026-10-27": {
                    "crypto": {"text": "BMNR <b>3,500,000 ETH</b>", "news": [{"title": "<img src=x>", "link": "https://a", "summary": "3,500,000 ETH"}]},
                    "macro": {"text": "FOMC 11/4", "news": []},
                },
            },
        }
        db = Mock()
        db.load_ticker.side_effect = lambda t: frames[t]
        db.load_json.side_effect = lambda name: stored.get(name)
        mocks = {}
        with ExitStack() as stack:
            for name, value in [("SKIP_LLM_AND_NEWS", skip), ("IS_TEST_REPORT", test),
                                ("TELEGRAM_BOT_TOKEN", "token"), ("TELEGRAM_CHAT_ID", "chat")]:
                stack.enter_context(patch.object(config, name, value))
            stack.enter_context(patch.object(report_store, "LOCAL_REPORT_DIR", self.reports_dir))
            stack.enter_context(patch.object(report_store, "LOCAL_WEEKLY_REPORT_DIR", self.weekly_dir))
            stack.enter_context(patch.object(static_export, "DOCS_DATA_DIR", self.data_dir))
            stack.enter_context(patch.object(weekly_briefing, "now_eastern_date", return_value=D(2026, 11, 1)))
            stack.enter_context(patch.object(weekly_pipeline.data_fetcher, "fetch_macro_history", return_value={
                "^VIX": pd.Series([20.0, 18.0], index=["2026-10-23", "2026-10-30"]),
            }))
            mocks["chat"] = stack.enter_context(patch.object(briefing, "_call_chat", return_value=llm_reply))
            mocks["exa"] = stack.enter_context(patch.object(weekly_briefing, "fetch_fresh_theme_news", return_value=[]))
            mocks["telegram"] = stack.enter_context(patch.object(telegram, "send_message"))
            stack.enter_context(patch.dict(os.environ, {"GITHUB_OUTPUT": ""}))
            result = weekly_pipeline.run_weekly_report(db, week=week)
        return result, mocks

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_scheduled_run_publishes_both_pages_index_and_telegram(self):
        result, mocks = self._run()
        self.assertEqual(result["week"], "2026-W44")
        self.assertTrue(result["asset_path"].endswith(os.path.join("weekly", "2026-W44.html")))
        self.assertTrue(result["special_path"].endswith("2026-W44-special.html"))
        mocks["exa"].assert_called()
        mocks["telegram"].assert_called_once()
        message = mocks["telegram"].call_args.args[0]
        self.assertIn("weekly/2026-W44.html", message)
        self.assertIn("weekly/2026-W44-special.html", message)

        html = self._read(result["asset_path"])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("../2026-10-26.html", html)
        self.assertNotIn("../2026-10-30.html", html)  # not on disk
        self.assertIn("10/26~10/30", html)
        self.assertNotIn("<td>2026-11-02</td>", html)  # history after the week is never read

        special = self._read(result["special_path"])
        self.assertNotIn("<img src=x>", special)
        self.assertNotIn("<b>3,500,000", special)

        with open(os.path.join(self.data_dir, "weekly_reports.json"), encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(index, [{
            "week": "2026-W44", "period": "10/26~10/30",
            "asset_url": "reports/weekly/2026-W44.html", "special_url": "reports/weekly/2026-W44-special.html",
        }])

    def test_skip_omits_special_page_and_paid_calls(self):
        result, mocks = self._run(skip=True)
        self.assertIsNone(result["special_path"])
        mocks["chat"].assert_not_called()
        mocks["exa"].assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.weekly_dir, "2026-W44-special.html")))
        self.assertIn("특별 섹션 주간 리포트는 이번 주 생성되지 않았습니다", self._read(result["asset_path"]))

    def test_test_run_uses_suffix_and_skips_index_and_telegram(self):
        result, mocks = self._run(test=True)
        self.assertTrue(result["asset_path"].endswith("2026-W44_test.html"))
        self.assertTrue(result["special_path"].endswith("2026-W44-special_test.html"))
        self.assertIn("2026-W44-special_test.html", self._read(result["asset_path"]))
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "weekly_reports.json")))
        mocks["telegram"].assert_not_called()

    def test_historical_week_skips_telegram_and_fresh_search(self):
        result, mocks = self._run(week="2026-W44")
        mocks["telegram"].assert_not_called()
        mocks["exa"].assert_not_called()
        self.assertIsNotNone(result["special_path"])

    def test_unfinished_week_rejected(self):
        with self.assertRaises(ValueError):
            self._run(week="2026-W45")

    def test_index_upserts_newest_first_and_daily_index_ignores_weekly(self):
        os.makedirs(self.weekly_dir)
        for name in ("2026-W43.html", "2026-W44.html"):
            open(os.path.join(self.weekly_dir, name), "w").close()
        with patch.object(config, "IS_TEST_REPORT", False), \
                patch.object(report_store, "LOCAL_REPORT_DIR", self.reports_dir), \
                patch.object(report_store, "LOCAL_WEEKLY_REPORT_DIR", self.weekly_dir), \
                patch.object(static_export, "DOCS_DATA_DIR", self.data_dir):
            static_export.export_weekly_reports_index("2026-W43", "10/19~10/23")
            static_export.export_weekly_reports_index("2026-W44", "10/26~10/30")
            index = static_export.export_weekly_reports_index("2026-W44", "10/26~10/30")
            static_export.export_reports_index({})
        self.assertEqual([e["week"] for e in index], ["2026-W44", "2026-W43"])
        self.assertIsNone(index[0]["special_url"])
        with open(os.path.join(self.data_dir, "reports.json"), encoding="utf-8") as f:
            daily = json.load(f)
        self.assertEqual([e["date"] for e in daily["dates"]], sorted(W44_DAYS[:3], reverse=True))


class TelegramWeeklyTests(unittest.TestCase):
    def test_summary_escapes_markdown_and_links_pages(self):
        text = telegram.format_weekly_summary(
            "2026-W44", "10/26~10/30", "my_var *bold* [x]", "혼조",
            {"SPY": 1.0, "TLT": -2.0}, {"QQQ": [("2026-10-28", "HOLD", "매수")]}, "https://a/w.html", None,
        )
        self.assertIn("my\\_var \\*bold\\* \\[x]", text)
        self.assertIn("최고 SPY +1.00% · 최저 TLT -2.00%", text)
        self.assertIn("QQQ HOLD→매수", text)
        self.assertIn("(https://a/w.html)", text)
        self.assertNotIn("특별 섹션", text)
        self.assertLessEqual(len(text.splitlines()), 7)


class RenderEscapingTests(unittest.TestCase):
    def test_special_page_escapes_llm_text_and_news(self):
        window = weekly_calc.WeekWindow("2026-W44", W44_DAYS, "2026-10-23")
        theme = {
            "label": "크립토", "assets": ("ETH-USD",), "record_days": [], "texts_days": [], "fresh": [],
            "flows": {"반복": "<script>x</script>", "신규": "a", "소멸": "b"},
            "numbers": [{"metric": "<i>m</i>", "value": "1", "as_of": "d", "source": "s"}], "numbers_dropped": 1,
            "connection": "c", "next_week": "n", "source": "llm",
            "news": [{"title": "t", "link": "https://x/'onmouseover='y"}],
        }
        special = {"themes": {"crypto": theme}, "highlights": "<b>h</b>", "next_week": "n", "source": "llm"}
        stats = {"ETH-USD": {"return_pct": 1.0}}
        grid = {d: {"ETH-USD": "HOLD"} for d in W44_DAYS}
        html = weekly_report.build_weekly_special_html(window, special, stats, grid, "2026-W44.html")
        for raw in ("<script>x</script>", "<i>m</i>", "<b>h</b>", "'onmouseover='"):
            self.assertNotIn(raw, html)
        self.assertIn("제외했습니다", html)


if __name__ == "__main__":
    unittest.main()

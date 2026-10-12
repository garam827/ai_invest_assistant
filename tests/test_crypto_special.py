import unittest
from unittest.mock import Mock, patch

from invest_assistant import config
from invest_assistant import universe
from invest_assistant.data import news as news_fetcher
from invest_assistant.recommendations import engine
from invest_assistant.reporting import report


def _item(title, link):
    return {"title": title, "summary": "s", "publisher": "p", "link": link, "published_at": None}


class CryptoSpecialBriefingTest(unittest.TestCase):
    def test_ethereum_is_a_representative_crypto_asset(self):
        self.assertEqual(universe.ASSET_CLASS_TICKERS["ETH-USD"]["category"], "암호화폐")
        self.assertEqual(len(universe.ASSET_CLASS_TICKERS), 13)

    def test_fetches_each_keyword_tags_dedupes_and_caches(self):
        db = Mock()
        fetched = {
            news_fetcher.CRYPTO_NEWS_QUERIES["RWA"]: [_item("rwa", "https://a"), _item("dup", "https://x")],
            news_fetcher.CRYPTO_NEWS_QUERIES["비트마인"]: [_item("bmnr", "https://b"), _item("dup", "https://x")],
        }
        with patch.object(config, "SKIP_LLM_AND_NEWS", False), \
                patch.object(news_fetcher, "get_cached_news", return_value=None), \
                patch.object(news_fetcher, "fetch_ticker_news_exa", side_effect=lambda _k, query, **_: fetched[query]), \
                patch.object(news_fetcher, "archive_news") as archive, \
                patch.object(engine.llm_briefing, "generate_crypto_special_briefing", return_value="digest") as llm:
            result = engine.get_crypto_special_briefing(db)

        self.assertEqual(result["text"], "digest")
        self.assertEqual([(i["title"], i["keyword"]) for i in result["news"]],
                         [("rwa", "RWA"), ("dup", "RWA"), ("bmnr", "비트마인")])
        archive.assert_called_once_with(db, news_fetcher.CRYPTO_NEWS_ARCHIVE_KEY, result["news"])
        by_keyword = llm.call_args.args[0]
        self.assertEqual([i["title"] for i in by_keyword["비트마인"]], ["bmnr"])

    def test_skip_flag_avoids_paid_calls(self):
        with patch.object(config, "SKIP_LLM_AND_NEWS", True), \
                patch.object(news_fetcher, "fetch_ticker_news_exa") as exa:
            self.assertIsNone(engine.get_crypto_special_briefing(Mock()))
        exa.assert_not_called()


class CryptoSpecialReportTest(unittest.TestCase):
    def test_section_is_escaped_and_mirrored_in_markdown(self):
        crypto = {"text": "<b>RWA</b> 소식", "news": [_item("t", "https://a")]}
        html = report._build_crypto_special_html(crypto)
        self.assertIn(report.CRYPTO_SPECIAL_TITLE, html)
        self.assertIn("&lt;b&gt;RWA&lt;/b&gt;", html)
        self.assertEqual(report._build_crypto_special_html(None), "")
        markdown = report._build_report_markdown("2026-10-12", "", {}, None, None, crypto_special=crypto)
        self.assertIn(f"## {report.CRYPTO_SPECIAL_TITLE}", markdown)

    def test_report_no_longer_has_backtest_section(self):
        self.assertFalse(hasattr(report, "_build_backtest_summary_html"))
        with patch.object(report, "_build_signal_sections_html", return_value=""), \
                patch.object(report, "_build_hold_charts_html", return_value=""):
            html = report.build_daily_report_html(
                Mock(), {"SPY": {"date": "2026-10-12", "action": "HOLD", "close": 1.0}},
                crypto_special={"text": "digest", "news": []},
            )
        self.assertNotIn("백테스트", html)
        self.assertIn(report.CRYPTO_SPECIAL_TITLE, html)


if __name__ == "__main__":
    unittest.main()

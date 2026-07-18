"""Shared 'Mr. Serenity' recommendation logic (news + signal state -> 매수/HOLD/매도).

The 매수/HOLD/매도 action is always decided mechanically (signal_engine.get_mechanical_action,
no network call) — the LLM/Exa news call only runs on a 매수/매도 day, to add a narrative
explanation, and is skipped entirely on HOLD days (the common case) to keep OpenRouter/Exa
usage low and immune to rate limits.

Streamlit-independent so the exact same logic can run from app.py's chart tabs (cached,
one ticker at a time, on user demand) and from a cron job (batch, no caching needed since
it only runs once/day). CLI entry point runs the batch version for data_fetcher.ASSET_CLASS_TICKERS
only — not all 500+ S&P 500 stocks, to keep LLM/news API usage bounded.

If TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are configured, run_asset_class_recommendations also
sends a Telegram summary (all tickers) + a chart image per 매수/매도 ticker (see
telegram_notifier.py) — cron-only, not triggered by the interactive Streamlit UI.
"""
from __future__ import annotations

import datetime
import logging

import pandas as pd

import config
import data_fetcher
import news_fetcher
import openrouter_briefing
import signal_engine
import telegram_notifier
from drive_db import DriveDB

logger = logging.getLogger(__name__)

RECOMMENDATIONS_FILENAME_PREFIX = "_recommendations_"


def _is_data_fresh(raw_df: pd.DataFrame, max_age_days: int = config.DATA_FRESHNESS_MAX_AGE_DAYS) -> bool:
    """True if the most recent stored bar is within max_age_days of now.

    Guards against generating a recommendation from stale data when collection silently
    failed for one ticker (data_fetcher logs and skips per-ticker errors rather than
    failing the whole run, so a green workflow run doesn't guarantee every ticker updated).
    """
    last_date = pd.to_datetime(raw_df["Date"]).max()
    age_days = (pd.Timestamp.now(tz="UTC").tz_localize(None) - last_date).days
    return age_days <= max_age_days


def get_recommendation_for_ticker(drive_db: DriveDB, ticker: str) -> dict | None:
    """Get a 매수/HOLD/매도 call for one ticker.

    The action itself always comes from signal_engine.get_mechanical_action — deterministic,
    no network call. On a HOLD day (the common case for a slow-moving trend-following system)
    that's all we return: no news fetch, no LLM call, nothing that can rate-limit. Only on a
    매수/매도 day do we fetch news (Exa) and ask the LLM for a narrative explanation — the LLM's
    own parsed action is logged if it disagrees, but never overrides the mechanical one.

    Returns None if the ticker has no data in Drive yet, or if that data is stale
    (see _is_data_fresh) — a stale-data recommendation would be misleading.
    """
    raw_df = drive_db.load_ticker(ticker)
    if raw_df is None or raw_df.empty:
        return None
    if not _is_data_fresh(raw_df):
        logger.warning(
            "%s data is stale (last bar %s), skipping recommendation", ticker, raw_df["Date"].max()
        )
        return None

    summary = signal_engine.get_latest_signal_summary(raw_df)
    action = signal_engine.get_mechanical_action(summary)

    if action == "HOLD":
        return {
            "ticker": ticker,
            "action": "HOLD",
            "text": "오늘은 매수 돌파도 청산 시그널도 발생하지 않아 HOLD입니다. (기계적 규칙 기반 판정 — 뉴스/LLM 분석은 매수·매도 시그널이 발생한 날에만 수행합니다.)",
            "news": [],
            "close": summary["close"],
            "date": str(summary["date"]),
        }

    news = news_fetcher.fetch_ticker_news_exa(ticker)
    news_fetcher.archive_news(drive_db, ticker, news)
    reco = openrouter_briefing.generate_recommendation(ticker, news, summary)

    if reco["action"] != action:
        logger.warning(
            "%s: LLM action (%s) disagreed with mechanical rule (%s) — using the mechanical one",
            ticker,
            reco["action"],
            action,
        )

    return {
        "ticker": ticker,
        "action": action,
        "text": reco["text"],
        "news": news,
        "close": summary["close"],
        "date": str(summary["date"]),
    }


def run_asset_class_recommendations(drive_db: DriveDB, tickers: dict | None = None) -> dict:
    """Run get_recommendation_for_ticker for each representative asset-class ticker
    (data_fetcher.ASSET_CLASS_TICKERS by default — NOT the full S&P 500 universe), and
    persist the day's results to Drive as `_recommendations_{date}.json`.
    """
    tickers = tickers if tickers is not None else data_fetcher.ASSET_CLASS_TICKERS
    logger.info("Starting asset-class recommendations for %d tickers", len(tickers))

    results: dict[str, dict] = {}
    for ticker in tickers:
        try:
            reco = get_recommendation_for_ticker(drive_db, ticker)
            if reco is None:
                logger.warning("No data (or stale data) for %s, skipping recommendation", ticker)
                continue
            results[ticker] = reco
            logger.info("%s -> 추천: %s", ticker, reco["action"])
        except Exception:
            logger.exception("Failed to generate recommendation for %s", ticker)

    date = datetime.date.today().isoformat()
    try:
        drive_db.save_json(f"{RECOMMENDATIONS_FILENAME_PREFIX}{date}.json", results)
        logger.info("Saved %d recommendations to _recommendations_%s.json", len(results), date)
    except Exception:
        # Don't let a transient Drive/network failure on the final save discard the
        # per-ticker work already done — the caller still gets the in-memory results.
        logger.exception("Failed to persist recommendations to Drive (results still returned)")

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            telegram_notifier.notify_recommendations(drive_db, results)
        except Exception:
            logger.exception("Failed to send Telegram notifications (results still returned)")
    else:
        logger.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set, skipping Telegram notification")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_asset_class_recommendations(DriveDB())

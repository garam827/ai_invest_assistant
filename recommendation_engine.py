"""Shared 'Mr. Serenity' recommendation logic (news + signal state -> 매수/HOLD/매도).

Streamlit-independent so the exact same logic can run from app.py's chart tabs (cached,
one ticker at a time, on user demand) and from a cron job (batch, no caching needed since
it only runs once/day). CLI entry point runs the batch version for data_fetcher.ASSET_CLASS_TICKERS
only — not all 500+ S&P 500 stocks, to keep LLM/news API usage bounded.
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
    """Fetch news (Exa), archive it, and get a mechanical 매수/HOLD/매도 call for one ticker.

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

    news = news_fetcher.fetch_ticker_news_exa(ticker)
    news_fetcher.archive_news(drive_db, ticker, news)
    summary = signal_engine.get_latest_signal_summary(raw_df)
    reco = openrouter_briefing.generate_recommendation(ticker, news, summary)

    return {
        "ticker": ticker,
        "action": reco["action"],
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
                logger.warning("No data for %s yet, skipping recommendation", ticker)
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

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_asset_class_recommendations(DriveDB())

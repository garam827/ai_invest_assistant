"""Collect and synchronize market data in Drive."""
from __future__ import annotations

import argparse
import logging
import time

import pandas as pd

from invest_assistant import config
from invest_assistant.data.market import (
    _fetch_sp500_table,
    fetch_ohlcv,
    get_sp500_tickers,
)
from invest_assistant.storage.drive import DriveDB
from invest_assistant.universe import ASSET_CLASS_TICKERS, UNIVERSE_FILENAME

logger = logging.getLogger(__name__)

def run_initial_ingestion(drive_db: DriveDB, tickers: list[str] | None = None, end: str | None = None) -> None:
    """First-run backfill: pull config.INITIAL_HISTORY_PERIOD of history per ticker and store to Drive."""
    tickers = tickers or get_sp500_tickers()
    logger.info("Starting initial ingestion for %d tickers", len(tickers))

    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker, period=config.INITIAL_HISTORY_PERIOD, end=end)
            if df.empty:
                logger.warning("No data returned for %s, skipping", ticker)
                continue
            drive_db.save_ticker(ticker, df)
            logger.info("Saved %s (%d rows)", ticker, len(df))
        except Exception:
            logger.exception("Failed to ingest %s", ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)

def sync_universe(drive_db: DriveDB, end: str | None = None) -> dict:
    """Reconcile Drive's stored tickers against the live S&P 500 constituent list.

    New entrants get a full history backfill so Donchian/ATR windows are populated
    before they join the daily update flow. Removed entrants are NOT deleted (their
    history stays for reference) but are dropped from the active list stored in
    UNIVERSE_FILENAME, so run_daily_update and the signal dashboard stop tracking them.
    """
    table = _fetch_sp500_table()
    current_sp500 = set(table["Symbol"])
    sector_map = dict(zip(table["Symbol"], table["GICS Sector"]))
    # "회사명 (세부업종)" — a lightweight per-ticker description built from data we already
    # scrape, no extra requests. Shown as the S&P 500 chart tab's subtitle (see app.py).
    description_map = {
        row["Symbol"]: f"{row['Security']} ({row['GICS Sub-Industry']})" for _, row in table.iterrows()
    }
    # Exclude asset-class ETF proxies from S&P membership accounting entirely — they're never
    # S&P 500 constituents, so without this they'd get diffed as "removed" on every sync.
    stored = set(drive_db.list_tickers()) - set(ASSET_CLASS_TICKERS)

    to_add = sorted(current_sp500 - stored)
    inactive = sorted(stored - current_sp500)

    if to_add:
        logger.info("Universe sync: %d new S&P 500 ticker(s) to backfill: %s", len(to_add), to_add)
        run_initial_ingestion(drive_db, tickers=to_add, end=end)

    active = sorted(current_sp500 & (stored | set(to_add)))
    drive_db.save_json(
        UNIVERSE_FILENAME,
        {
            "active_tickers": active,
            "inactive_tickers": inactive,
            "sectors": {ticker: sector_map[ticker] for ticker in active},
            "descriptions": {ticker: description_map[ticker] for ticker in active},
            "synced_at": pd.Timestamp.utcnow().isoformat(),
        },
    )
    logger.info("Universe sync complete: %d active, %d inactive (kept for history)", len(active), len(inactive))
    return {"active": active, "added": to_add, "inactive": inactive}

def _update_one_ticker(drive_db: DriveDB, ticker: str, end: str | None = None) -> None:
    """Fetch since the ticker's last stored date (or a full backfill if it has no data yet) and upsert."""
    existing = drive_db.load_ticker(ticker)
    if existing is not None and not existing.empty:
        last_date = pd.to_datetime(existing["Date"]).max()
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        new_df = fetch_ohlcv(ticker, start=start, end=end)
    else:
        new_df = fetch_ohlcv(ticker, period=config.INITIAL_HISTORY_PERIOD, end=end)

    if new_df.empty:
        logger.info("No new data for %s", ticker)
        return

    merged = drive_db.upsert_ticker(ticker, new_df)
    latest = merged.iloc[-1]
    logger.info("Updated %s (%d total rows; latest=%s close=%s)",
                ticker, len(merged), latest["Date"], latest["Close"])

def run_daily_update(drive_db: DriveDB, tickers: list[str] | None = None, end: str | None = None) -> None:
    """Fetch the latest bar(s) per ticker and upsert into its Drive-backed Parquet file."""
    if tickers is None:
        universe = drive_db.load_json(UNIVERSE_FILENAME)
        tickers = (universe or {}).get("active_tickers") or drive_db.list_tickers() or get_sp500_tickers()
    logger.info("Starting daily update for %d tickers", len(tickers))

    for ticker in tickers:
        try:
            _update_one_ticker(drive_db, ticker, end=end)
        except Exception:
            logger.exception("Failed to update %s", ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)

def run_asset_class_update(drive_db: DriveDB, end: str | None = None) -> None:
    """Backfill (first run) or update (subsequent runs) the representative asset-class ETF proxies."""
    logger.info("Starting asset-class update for %d tickers", len(ASSET_CLASS_TICKERS))
    failed = []
    for ticker in ASSET_CLASS_TICKERS:
        try:
            _update_one_ticker(drive_db, ticker, end=end)
        except Exception:
            logger.exception("Failed to update asset-class ticker %s", ticker)
            failed.append(ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)
    if failed:
        raise RuntimeError(f"Asset-class collection incomplete: {', '.join(failed)}")

def run_full_collection(drive_db: DriveDB, end: str | None = None) -> dict:
    """One button's worth of work: S&P 500 membership sync + daily update + asset-class ETF update.

    `end` (YYYY-MM-DD, exclusive): normally unset for the daily cron (fetch everything new,
    unbounded). Pass it for a one-off manual catch-up that must not pull in a later trading
    day's data than the run being recovered was meant to see -- see fetch_ohlcv's docstring.
    """
    sync_result = sync_universe(drive_db, end=end)
    run_daily_update(drive_db, end=end)
    run_asset_class_update(drive_db, end=end)
    return sync_result

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Collect S&P 500 OHLCV data into Drive-backed Parquet files.")
    parser.add_argument(
        "mode",
        choices=["init", "update", "sync"],
        help="init = full history backfill, update = sync universe + daily append, sync = reconcile S&P 500 membership only",
    )
    args = parser.parse_args()

    db = DriveDB()
    if args.mode == "init":
        run_initial_ingestion(db)
        run_asset_class_update(db)
    elif args.mode == "sync":
        sync_universe(db)
    else:
        run_full_collection(db)

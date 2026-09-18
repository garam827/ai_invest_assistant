"""Collect and synchronize market data in Drive."""
from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local

import pandas as pd

from invest_assistant import config
from invest_assistant.data.market import (
    _fetch_sp500_table,
    fetch_ohlcv,
    get_sp500_tickers,
)
from invest_assistant.data.quality import validate_ohlcv
from invest_assistant.storage.drive import DriveDB
from invest_assistant.storage.runtime import (
    require_private_operation,
    ticker_transaction,
)
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

@ticker_transaction
def _update_one_ticker(drive_db: DriveDB, ticker: str, end: str | None = None) -> dict:
    """Hold the ticker transaction across read, fetch, merge, and save."""
    started = time.monotonic()
    existing = drive_db.load_ticker(ticker)
    read_done = time.monotonic()
    if existing is not None and not existing.empty:
        last_date = pd.to_datetime(existing["Date"]).max()
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        new_df = fetch_ohlcv(ticker, start=start, end=end)
    else:
        new_df = fetch_ohlcv(ticker, period=config.INITIAL_HISTORY_PERIOD, end=end)
    validate_ohlcv(new_df)  # Empty/invalid responses cannot count as success.
    fetched = time.monotonic()
    frames = [existing, new_df] if existing is not None and not existing.empty else [new_df]
    merged = (pd.concat(frames, ignore_index=True).drop_duplicates(subset="Date", keep="last")
              .sort_values("Date").reset_index(drop=True))
    validate_ohlcv(merged)
    drive_db.save_ticker(ticker, merged)
    finished = time.monotonic()
    timings = {"read_sec": read_done - started, "yahoo_including_wait_sec": fetched - read_done,
               "merge_save_sec": finished - fetched, "total_sec": finished - started}
    logger.info("Updated %s (%d rows; latest=%s); timings=%s", ticker, len(merged), merged.iloc[-1]["Date"], timings)
    return timings


def _run_updates(drive_db, tickers, end=None) -> dict:
    """Each worker owns its Drive transport; YahooGate serializes Yahoo only."""
    require_private_operation()
    workers = config.COLLECTION_WORKERS
    rounds = config.COLLECTION_RETRY_ROUNDS
    if not 1 <= workers <= 8 or not 0 <= rounds <= 3 or config.COLLECTION_RETRY_DELAY_SEC < 0:
        raise ValueError("Collection requires workers=1..8, retry_rounds=0..3, nonnegative retry delay")
    pending = list(dict.fromkeys(tickers))
    total = len(pending)
    results = {}
    state = local()
    clients = []
    started = time.monotonic()

    def update(ticker):
        if workers == 1:
            db = drive_db
        else:
            if not hasattr(state, "db"):
                state.db = drive_db.new_worker()
                clients.append(state.db)
            db = state.db
        return _update_one_ticker(db, ticker, end=end)

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collect") as pool:
            for attempt in range(1, rounds + 2):
                if not pending:
                    break
                if attempt > 1:
                    delay = config.COLLECTION_RETRY_DELAY_SEC * 2 ** (attempt - 2)
                    logger.info("Retrying %d failed tickers after %.1fs", len(pending), delay)
                    time.sleep(delay)
                futures = {pool.submit(update, ticker): ticker for ticker in pending}
                failed = []
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        timings = future.result()
                        results[ticker] = {"status": "updated", "attempts": attempt, "timings": timings}
                    except Exception as exc:
                        failed.append(ticker)
                        results[ticker] = {"status": "failed", "attempts": attempt,
                                           "error_type": type(exc).__name__}
                        logger.exception("Collection failed for %s (round %d)", ticker, attempt)
                    # Main thread emits progress so Streamlit can safely display buffered logs.
                    logger.info("Collection progress: %d/%d; %s=%s", len(results), total, ticker, results[ticker]["status"])
                pending = failed
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                logger.warning("Failed to close a collection client", exc_info=True)
    failed = sorted(t for t, result in results.items() if result["status"] == "failed")
    report = {"results": results, "failed": failed, "elapsed_sec": time.monotonic() - started, "workers": workers}
    logger.info("Collection finished: total=%d updated=%d failed=%d elapsed=%.2fs workers=%d",
                len(results), len(results) - len(failed), len(failed), report["elapsed_sec"], workers)
    return report


def run_daily_update(drive_db: DriveDB, tickers: list[str] | None = None, end: str | None = None) -> dict:
    if tickers is None:
        universe = drive_db.load_json(UNIVERSE_FILENAME)
        tickers = (universe or {}).get("active_tickers") or drive_db.list_tickers() or get_sp500_tickers()
    return _run_updates(drive_db, tickers, end=end)


def run_asset_class_update(drive_db: DriveDB, end: str | None = None) -> dict:
    report = _run_updates(drive_db, list(ASSET_CLASS_TICKERS), end=end)
    if report["failed"]:
        raise RuntimeError(f"Asset-class collection incomplete: {', '.join(report['failed'])}")
    return report


def run_full_collection(drive_db: DriveDB, end: str | None = None) -> dict:
    """One button's worth of work: S&P 500 membership sync + daily update + asset-class ETF update.

    `end` (YYYY-MM-DD, exclusive): normally unset for the daily cron (fetch everything new,
    unbounded). Pass it for a one-off manual catch-up that must not pull in a later trading
    day's data than the run being recovered was meant to see -- see fetch_ohlcv's docstring.
    """
    sync_result = sync_universe(drive_db, end=end)
    daily = run_daily_update(drive_db, end=end)
    assets = run_asset_class_update(drive_db, end=end)
    return {**sync_result, "collection": {"stocks": daily, "assets": assets}}

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

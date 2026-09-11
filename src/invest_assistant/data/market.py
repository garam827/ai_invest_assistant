"""Read market prices, S&P 500 membership, and macro indicators.

Collection orchestration lives in invest_assistant.pipelines.collect; instrument
metadata lives in invest_assistant.universe. These requests do not write to Drive.
"""
from __future__ import annotations

import io
import logging
import time

import pandas as pd
import requests
import yfinance as yf

from invest_assistant.data.quality import validate_ohlcv
from invest_assistant.universe import MACRO_TICKERS

logger = logging.getLogger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OHLCV_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]

def fetch_macro_snapshot() -> dict:
    """Fresh macro-context snapshot for the daily report: VIX + short/mid/long US Treasury
    yields.

    Pulled live every time this is called (not cached/stored to Drive -- these change
    intraday and the report only needs "as of report-build time"). Returns
    {ticker: {"label": ..., "format": "index"|"yield_pct", "value": float,
    "prior_value": float | None, "as_of": "YYYY-MM-DD"}}; "prior_value" is the previous
    trading day's close, for a simple delta in the report. yfinance's ^IRX/^TNX/^TYX closes
    are already yields in percent (e.g. 4.736 == 4.736%), not the historical CBOE "yield x10"
    quoting convention -- no extra scaling needed.

    A per-ticker fetch failure is skipped, not fatal -- same "an optional section just gets
    omitted, the rest of the report/pipeline is unaffected" pattern as every other optional
    section in this project.
    """
    snapshot = {}
    for ticker, meta in MACRO_TICKERS.items():
        try:
            history = yf.Ticker(ticker).history(period="5d", interval="1d")
            if history.empty:
                continue
            closes = history["Close"]
            snapshot[ticker] = {
                "label": meta["label"],
                "format": meta["format"],
                "value": float(closes.iloc[-1]),
                "prior_value": float(closes.iloc[-2]) if len(closes) >= 2 else None,
                "as_of": closes.index[-1].strftime("%Y-%m-%d"),
            }
        except Exception:
            logger.exception("Failed to fetch macro snapshot for %s", ticker)

    return snapshot


def _fetch_sp500_table() -> pd.DataFrame:
    """Scrape the current S&P 500 constituent table from Wikipedia (Symbol + GICS Sector, among others)."""
    # Wikipedia blocks urllib's default user agent (403); fetch with a browser-like one instead.
    response = requests.get(SP500_WIKI_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    table = pd.read_html(io.StringIO(response.text))[0]
    table["Symbol"] = table["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False)
    return table


def get_sp500_tickers() -> list[str]:
    """Current S&P 500 ticker symbols, normalized for yfinance (e.g. BRK.B -> BRK-B)."""
    return sorted(_fetch_sp500_table()["Symbol"].tolist())


def fetch_ohlcv(
    ticker: str, period: str | None = None, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Fetch daily OHLCV for one ticker. Pass either `period` (e.g. '5y') or `start` (YYYY-MM-DD).

    `end` (YYYY-MM-DD, exclusive per yfinance's own convention) is normally left unset -- the
    daily cron always wants "everything new," never a capped window. It exists for one-off manual
    backfills where a later trading day's data must not leak in yet (e.g. recovering a missed
    run without accidentally also pulling a day that hadn't closed when that run should have
    happened) -- see run_daily_update/run_asset_class_update/run_full_collection's own `end` param.
    """
    for attempt in range(3):
        history = yf.Ticker(ticker).history(
            period=period, start=start, end=end, interval="1d", auto_adjust=True
        )
        if history.empty:
            return history
        history = history.reset_index()[OHLCV_COLUMNS]
        history["Date"] = pd.to_datetime(history["Date"]).dt.tz_localize(None)
        try:
            validate_ohlcv(history)
        except ValueError:
            logger.warning("%s: invalid OHLCV response (attempt %d/3)", ticker, attempt + 1)
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
            continue
        return history

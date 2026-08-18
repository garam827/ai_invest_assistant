"""S&P 500 ticker list + yfinance daily OHLCV collection, plus a fixed set of asset-class
ETF/spot proxies (see ASSET_CLASS_TICKERS) tracked independently of S&P 500 membership.

Entry points, matching the spec's data flow:
- run_initial_ingestion: first-run 5y backfill per S&P 500 ticker.
- sync_universe: reconcile Drive's stored S&P 500 tickers against membership changes.
- run_daily_update: fetch only what's new since each ticker's last stored date, for the
  active S&P 500 universe (see sync_universe).
- run_asset_class_update: same delta-fetch logic as run_daily_update, for ASSET_CLASS_TICKERS.
- run_full_collection: sync_universe + run_daily_update + run_asset_class_update in one call
  (what the Streamlit "데이터 적재" button and `python data_fetcher.py update` both run).
"""
from __future__ import annotations

import argparse
import io
import logging
import time

import pandas as pd
import requests
import yfinance as yf

import config
from drive_db import DriveDB

logger = logging.getLogger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OHLCV_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]
UNIVERSE_FILENAME = "_universe.json"

# Representative, liquid ETF (or spot, for BTC) proxies for major asset classes — raw indices
# (e.g. ^GSPC) or yield quotes (e.g. ^TNX) aren't directly tradable and often lack reliable
# volume data, so we track a tradable instrument instead. Fixed set, independent of S&P 500
# membership (never touched by sync_universe's diffing).
# Each entry: {"label": 표시명, "category": 분류, "description": 이 종목이 무엇인지 한 줄 설명,
# "news_query": Exa 검색용 매크로 지향 쿼리}. news_query가 없으면(개별 S&P 500 종목 등)
# news_fetcher.fetch_ticker_news_exa가 기본값 "{ticker} stock news"를 쓴다 — 이건 티커 자체가
# 회사이므로 적절하지만, ETF 프록시(예: GLD)는 "GLD stock news"로 검색하면 "GLD 몇 % 하락"류의
# 단순 가격 기사만 나오고 그 등락을 설명하는 매크로 뉴스(금리·달러·중앙은행 수요 등)는 안 나온다 —
# 그래서 프록시가 추종하는 실물 자산 이름으로 검색하도록 별도 쿼리를 둔다.
ASSET_CLASS_TICKERS = {
    "SPY": {
        "label": "S&P 500 (미국 대형주)",
        "category": "주식",
        "description": "S&P 500 지수를 추종하는 대표 ETF",
        "news_query": "S&P 500 stock market outlook analysis",
    },
    "QQQ": {
        "label": "나스닥 100 (Nasdaq-100)",
        "category": "주식",
        "description": "나스닥 상장 시가총액 상위 100대 비금융 기업에 투자하는 ETF (기술주 비중 높음)",
        "news_query": "Nasdaq tech stock market outlook analysis",
    },
    "BTC-USD": {
        "label": "비트코인 (Bitcoin)",
        "category": "암호화폐",
        "description": "비트코인 현물 가격(USD 기준)",
        "news_query": "bitcoin price outlook analysis",
    },
    "GLD": {
        "label": "금 (Gold)",
        "category": "귀금속",
        "description": "금 현물 가격을 추종하는 ETF",
        "news_query": "gold price outlook macro drivers analysis",
    },
    "TLT": {
        "label": "미국 장기국채 (20년+)",
        "category": "채권",
        "description": "만기 20년 이상 미국 국채에 투자하는 ETF",
        "news_query": "US long-term treasury bond yields outlook analysis",
    },
    "IEF": {
        "label": "미국 중기국채 (7-10년)",
        "category": "채권",
        "description": "만기 7~10년 미국 국채에 투자하는 ETF",
        "news_query": "US treasury bond yields outlook analysis",
    },
    "DBC": {
        "label": "원자재 종합 (Broad Commodities)",
        "category": "원자재",
        "description": "에너지·금속·농산물 등 원자재 선물에 분산 투자하는 종합 ETF",
        "news_query": "commodities market outlook analysis",
    },
    "USO": {
        "label": "원유 (Crude Oil)",
        "category": "원자재",
        "description": "WTI 원유 선물 가격을 추종하는 ETF",
        "news_query": "crude oil price outlook macro analysis",
    },
    "UNG": {
        "label": "천연가스 (Natural Gas)",
        "category": "원자재",
        "description": "천연가스 선물 가격을 추종하는 ETF",
        "news_query": "natural gas price outlook macro analysis",
    },
    "DBA": {
        "label": "농산물 (Agriculture)",
        "category": "원자재",
        "description": "옥수수·대두·밀·설탕 등 주요 농산물 선물에 분산 투자하는 ETF",
        "news_query": "agricultural commodities market outlook analysis",
    },
    "DBB": {
        "label": "기초금속 (Base Metals)",
        "category": "원자재",
        "description": "구리·알루미늄·아연 선물에 분산 투자하는 ETF (산업 수요 프록시, 경기 선행지표로도 참고됨)",
        "news_query": "base metals copper aluminum zinc price outlook macro analysis",
    },
    "UUP": {
        "label": "미국 달러 인덱스 (US Dollar Index)",
        "category": "통화",
        "description": "주요 6개국 통화 대비 미국 달러 강세를 추종하는 ETF",
        "news_query": "US dollar index DXY outlook macro analysis",
    },
}


# Pure market-context indicators for the daily report's macro snapshot (user request) --
# raw index/yield quotes, same "not directly tradable" reasoning as the ASSET_CLASS_TICKERS
# comment above, so they're deliberately NOT tracked like ASSET_CLASS_TICKERS: no Drive
# storage, no signal_engine, no trend-following signal of their own -- fetch_macro_snapshot
# below pulls a fresh live value at report-build time purely for display. Treasury yields
# span short/mid/long maturities (^IRX 13주 T-bill, ^TNX 10년, ^TYX 30년) per user request,
# not just the original 10-year alone.
MACRO_TICKERS = {
    "^VIX": {"label": "VIX (변동성지수)", "format": "index"},
    "^IRX": {"label": "美 13주 단기 국채금리", "format": "yield_pct"},
    "^TNX": {"label": "美 10년물 국채금리", "format": "yield_pct"},
    "^TYX": {"label": "美 30년 장기 국채금리", "format": "yield_pct"},
}

# ICE BofA US High Yield Index Option-Adjusted Spread -- the standard reference series for
# "하이일드 스프레드" (junk bond yield premium over Treasuries, in percentage points). Not
# available via yfinance, so pulled separately from FRED's public CSV export endpoint (no
# API key required, same "raw requests, no SDK" style as news_fetcher/openrouter_briefing).
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_HY_SPREAD_SERIES = "BAMLH0A0HYM2"


def fetch_high_yield_spread() -> dict | None:
    """Fresh High Yield bond spread (ICE BofA OAS, FRED series BAMLH0A0HYM2) -- same
    "pure display, not a signal" treatment as the yfinance-sourced entries in
    fetch_macro_snapshot, just from FRED since this series isn't on yfinance.

    FRED's CSV marks holidays/not-yet-published days with "." instead of a number -- those
    rows are dropped before picking the latest two values, so "prior_value" is always the
    previous *published* observation, not necessarily the previous calendar day.

    Returns None (not a dict) if the fetch/parse fails or yields no usable rows at all --
    fetch_macro_snapshot treats that the same as any other missing entry, section omitted.

    Retries once after a short pause -- this endpoint (unlike yfinance/Exa elsewhere in this
    project) was observed occasionally resetting the connection outright rather than
    returning an HTTP error, so a single bare attempt would drop the section more often than
    the data's actual availability warrants.
    """
    last_error: Exception | None = None
    response = None
    for attempt in range(2):
        try:
            response = requests.get(
                FRED_CSV_URL, params={"id": FRED_HY_SPREAD_SERIES}, timeout=30, headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(2)
    if response is None:
        raise last_error
    df = pd.read_csv(io.StringIO(response.text))
    df.columns = ["date", "value"]
    df = df[df["value"] != "."]
    if df.empty:
        return None
    df["value"] = df["value"].astype(float)
    latest, prior = df.iloc[-1], (df.iloc[-2] if len(df) >= 2 else None)
    return {
        "label": "하이일드 스프레드 (ICE BofA OAS)",
        "format": "spread_pct",
        "value": float(latest["value"]),
        "prior_value": float(prior["value"]) if prior is not None else None,
        "as_of": str(latest["date"]),
    }


def fetch_macro_snapshot() -> dict:
    """Fresh macro-context snapshot for the daily report: VIX, short/mid/long US Treasury
    yields, and the High Yield bond spread.

    Pulled live every time this is called (not cached/stored to Drive -- these change
    intraday and the report only needs "as of report-build time"). Returns
    {key: {"label": ..., "format": "index"|"yield_pct"|"spread_pct", "value": float,
    "prior_value": float | None, "as_of": "YYYY-MM-DD"}}; "prior_value" is the previous
    published value, for a simple delta in the report. yfinance's ^IRX/^TNX/^TYX closes are
    already yields in percent (e.g. 4.736 == 4.736%), not the historical CBOE "yield x10"
    quoting convention -- no extra scaling needed.

    A per-metric fetch failure (yfinance ticker or the separate FRED call) is skipped, not
    fatal -- same "an optional section just gets omitted, the rest of the report/pipeline is
    unaffected" pattern as every other optional section in this project.
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

    try:
        hy_spread = fetch_high_yield_spread()
        if hy_spread:
            snapshot["HY_SPREAD"] = hy_spread
    except Exception:
        logger.exception("Failed to fetch high yield spread")

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
    history = yf.Ticker(ticker).history(period=period, start=start, end=end, interval="1d")
    if history.empty:
        return history

    history = history.reset_index()[OHLCV_COLUMNS]
    history["Date"] = pd.to_datetime(history["Date"]).dt.tz_localize(None)
    return history


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
    logger.info("Updated %s (%d total rows)", ticker, len(merged))


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
    for ticker in ASSET_CLASS_TICKERS:
        try:
            _update_one_ticker(drive_db, ticker, end=end)
        except Exception:
            logger.exception("Failed to update asset-class ticker %s", ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)


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

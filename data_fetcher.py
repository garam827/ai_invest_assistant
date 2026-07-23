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
    "CPER": {
        "label": "구리 (Copper)",
        "category": "원자재",
        "description": "구리 선물 가격을 추종하는 ETF (경기 선행지표로도 참고됨)",
        "news_query": "copper price outlook macro analysis",
    },
    "UUP": {
        "label": "미국 달러 인덱스 (US Dollar Index)",
        "category": "통화",
        "description": "주요 6개국 통화 대비 미국 달러 강세를 추종하는 ETF",
        "news_query": "US dollar index DXY outlook macro analysis",
    },
}


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


def fetch_ohlcv(ticker: str, period: str | None = None, start: str | None = None) -> pd.DataFrame:
    """Fetch daily OHLCV for one ticker. Pass either `period` (e.g. '5y') or `start` (YYYY-MM-DD)."""
    history = yf.Ticker(ticker).history(period=period, start=start, interval="1d")
    if history.empty:
        return history

    history = history.reset_index()[OHLCV_COLUMNS]
    history["Date"] = pd.to_datetime(history["Date"]).dt.tz_localize(None)
    return history


def run_initial_ingestion(drive_db: DriveDB, tickers: list[str] | None = None) -> None:
    """First-run backfill: pull config.INITIAL_HISTORY_PERIOD of history per ticker and store to Drive."""
    tickers = tickers or get_sp500_tickers()
    logger.info("Starting initial ingestion for %d tickers", len(tickers))

    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker, period=config.INITIAL_HISTORY_PERIOD)
            if df.empty:
                logger.warning("No data returned for %s, skipping", ticker)
                continue
            drive_db.save_ticker(ticker, df)
            logger.info("Saved %s (%d rows)", ticker, len(df))
        except Exception:
            logger.exception("Failed to ingest %s", ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)


def sync_universe(drive_db: DriveDB) -> dict:
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
        run_initial_ingestion(drive_db, tickers=to_add)

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


def _update_one_ticker(drive_db: DriveDB, ticker: str) -> None:
    """Fetch since the ticker's last stored date (or a full backfill if it has no data yet) and upsert."""
    existing = drive_db.load_ticker(ticker)
    if existing is not None and not existing.empty:
        last_date = pd.to_datetime(existing["Date"]).max()
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        new_df = fetch_ohlcv(ticker, start=start)
    else:
        new_df = fetch_ohlcv(ticker, period=config.INITIAL_HISTORY_PERIOD)

    if new_df.empty:
        logger.info("No new data for %s", ticker)
        return

    merged = drive_db.upsert_ticker(ticker, new_df)
    logger.info("Updated %s (%d total rows)", ticker, len(merged))


def run_daily_update(drive_db: DriveDB, tickers: list[str] | None = None) -> None:
    """Fetch the latest bar(s) per ticker and upsert into its Drive-backed Parquet file."""
    if tickers is None:
        universe = drive_db.load_json(UNIVERSE_FILENAME)
        tickers = (universe or {}).get("active_tickers") or drive_db.list_tickers() or get_sp500_tickers()
    logger.info("Starting daily update for %d tickers", len(tickers))

    for ticker in tickers:
        try:
            _update_one_ticker(drive_db, ticker)
        except Exception:
            logger.exception("Failed to update %s", ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)


def run_asset_class_update(drive_db: DriveDB) -> None:
    """Backfill (first run) or update (subsequent runs) the representative asset-class ETF proxies."""
    logger.info("Starting asset-class update for %d tickers", len(ASSET_CLASS_TICKERS))
    for ticker in ASSET_CLASS_TICKERS:
        try:
            _update_one_ticker(drive_db, ticker)
        except Exception:
            logger.exception("Failed to update asset-class ticker %s", ticker)
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)


def run_full_collection(drive_db: DriveDB) -> dict:
    """One button's worth of work: S&P 500 membership sync + daily update + asset-class ETF update."""
    sync_result = sync_universe(drive_db)
    run_daily_update(drive_db)
    run_asset_class_update(drive_db)
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

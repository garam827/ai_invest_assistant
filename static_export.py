"""Static JSON export for the read-only React site (web/, published via GitHub Pages from
docs/data/). The React site never calls Drive/Exa/OpenRouter itself -- every value it shows
was already computed by the daily cron (recommendation_engine.run_asset_class_recommendations),
this module just serializes it to JSON.

Unlike docs/reports/{date}.html, nothing here is date-stamped: every file is *overwritten*
each run, since the React site only ever shows the latest snapshot (see CLAUDE.md's directory
notes for why -- avoids growing the repo forever). Every export function is a no-op when
config.IS_TEST_REPORT is set, same "a manual/sample run must never touch a real published
artifact" principle as report_builder's report_url gating.
"""
from __future__ import annotations

import json
import logging
import os

import pandas as pd

import chart_builder
import config
import data_fetcher
import openrouter_briefing
import signal_engine
from drive_db import DriveDB

logger = logging.getLogger(__name__)

DOCS_DATA_DIR = os.path.join("docs", "data")
CHARTS_DIR = os.path.join(DOCS_DATA_DIR, "charts")

# ~1.5 years of calendar days of chart history to export per ticker. signal_engine.compute_signals
# is always run on the ticker's *full* stored history first (see _chart_rows_for_ticker) so
# Donchian-100/ATR/Ichimoku warm-up isn't distorted -- this window only trims what's displayed,
# same pattern chart_builder.slice_to_period's other callers (app.py, report_builder.py) use.
CHART_EXPORT_WINDOW_DAYS = 500

CHART_COLUMNS = [
    "Date", "Open", "High", "Low", "Close", "Volume",
    "ATR", "Donchian_Upper_20", "Donchian_Lower_20", "Donchian_Upper_100", "Donchian_Lower_100",
    "Trailing_Stop", "BB_Upper", "BB_Lower", "BB_Middle",
    "Ichimoku_SenkouA", "Ichimoku_SenkouB", "Ichimoku_SenkouA_Raw", "Ichimoku_SenkouB_Raw",
    "Buy_Trigger", "Sell_Trigger", "Volume_Surge",
]
ROUND_DECIMALS = 4


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def export_signals_json(results: dict, sp500_signals: list[dict], signal_history: dict | None = None) -> None:
    """`results`: recommendation_engine.run_asset_class_recommendations's per-ticker output for
    the 12 ASSET_CLASS_TICKERS -- already carries the news/LLM narrative the cron computed once
    (results[ticker]['text']/['news']), reused as-is, never re-fetched here (same "don't
    re-call Exa/LLM for data already computed" rule report_builder/telegram_notifier follow).
    `sp500_signals`: recommendation_engine.get_sp500_signal_summary's output -- mechanical-only
    매수/매도 calls across the S&P 500, deliberately without news/LLM narrative.
    """
    if config.IS_TEST_REPORT:
        logger.info("IS_TEST_REPORT set, skipping static signals export")
        return

    asset_class_payload = []
    for ticker, reco in results.items():
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        asset_class_payload.append(
            {**reco, "label": meta.get("label", ticker), "category": meta.get("category", "")}
        )

    # One extra LLM call/day beyond what report_builder already makes for the HTML report --
    # accepted as a small, bounded cost rather than threading the already-built overview text
    # out of report_builder just to avoid it. Skipped under the same manual "don't burn API
    # quota" escape hatch as everywhere else in the cron.
    overview = None
    if not config.SKIP_LLM_AND_NEWS:
        try:
            overview = openrouter_briefing.generate_portfolio_overview(results, signal_history)
        except Exception:
            logger.exception("Failed to generate portfolio overview for static export")

    generated_at = pd.Timestamp.now(tz="UTC").isoformat()
    _write_json(
        os.path.join(DOCS_DATA_DIR, "signals_asset_class.json"),
        {"generated_at": generated_at, "overview": overview, "tickers": asset_class_payload},
    )
    _write_json(
        os.path.join(DOCS_DATA_DIR, "signals_sp500.json"),
        {"generated_at": generated_at, "signals": sp500_signals},
    )
    logger.info(
        "Exported signals_asset_class.json (%d tickers) and signals_sp500.json (%d signals)",
        len(asset_class_payload),
        len(sp500_signals),
    )


def export_universe_json(drive_db: DriveDB) -> None:
    """docs/data/universe.json -- ticker metadata for the React chart tab's category/sector
    -> ticker pickers. Not a copy of _universe.json verbatim: only the fields the picker needs."""
    if config.IS_TEST_REPORT:
        return

    universe = drive_db.load_json(data_fetcher.UNIVERSE_FILENAME) or {}
    sectors = universe.get("sectors", {})
    descriptions = universe.get("descriptions", {})
    active_tickers = sorted(universe.get("active_tickers", []))

    payload = {
        "asset_classes": [
            {"ticker": t, "label": m["label"], "category": m["category"], "description": m["description"]}
            for t, m in data_fetcher.ASSET_CLASS_TICKERS.items()
        ],
        "sp500": [
            {"ticker": t, "sector": sectors.get(t, ""), "description": descriptions.get(t, "")}
            for t in active_tickers
        ],
    }
    _write_json(os.path.join(DOCS_DATA_DIR, "universe.json"), payload)
    logger.info("Exported universe.json (%d S&P 500 tickers)", len(payload["sp500"]))


def _chart_rows_for_ticker(raw_df: pd.DataFrame) -> list[dict]:
    signals = signal_engine.compute_signals(raw_df)
    view = chart_builder.slice_to_period(signals, CHART_EXPORT_WINDOW_DAYS)[CHART_COLUMNS].copy()
    view["Date"] = view["Date"].dt.strftime("%Y-%m-%d")
    numeric_cols = [c for c in CHART_COLUMNS if c not in ("Date", "Buy_Trigger", "Sell_Trigger", "Volume_Surge")]
    view[numeric_cols] = view[numeric_cols].round(ROUND_DECIMALS)
    # pandas' to_json (unlike the stdlib json module) serializes NaN as JSON null, which is
    # what we actually want for the warm-up rows of a recently-added ticker's short history --
    # round-tripping through it here is simpler than hand-rolling NaN->None replacement.
    return json.loads(view.to_json(orient="records"))


def export_chart_data(drive_db: DriveDB, tickers: list[str] | None = None) -> None:
    """One JSON file per ticker (docs/data/charts/{ticker}.json), overwritten daily. Reuses
    signal_engine.compute_signals + chart_builder.slice_to_period exactly as
    chart_builder.build_ticker_chart_figure's callers do, so the exported series matches what
    the Streamlit/report chart actually draws. A single ticker's failure is skipped, same
    convention as every other bulk per-ticker loop in this codebase (data_fetcher, get_sp500_signal_summary).

    `tickers=None` (the default) covers the full chart universe: the 12 ASSET_CLASS_TICKERS
    plus every active S&P 500 ticker from _universe.json -- same 515-ticker set
    get_sp500_signal_summary iterates, computed independently here (a second Drive-read pass)
    since this needs the full signal series, not just the latest row.
    """
    if config.IS_TEST_REPORT:
        return

    if tickers is None:
        universe = drive_db.load_json(data_fetcher.UNIVERSE_FILENAME) or {}
        tickers = list(data_fetcher.ASSET_CLASS_TICKERS) + sorted(universe.get("active_tickers", []))

    os.makedirs(CHARTS_DIR, exist_ok=True)
    exported, skipped = 0, 0
    for ticker in tickers:
        try:
            raw_df = drive_db.load_ticker(ticker)
            if raw_df is None or raw_df.empty:
                skipped += 1
                continue
            rows = _chart_rows_for_ticker(raw_df)
            _write_json(os.path.join(CHARTS_DIR, f"{ticker}.json"), rows)
            exported += 1
        except Exception:
            logger.exception("Failed to export chart data for %s", ticker)
            skipped += 1
    logger.info("Exported chart data for %d tickers (%d skipped)", exported, skipped)

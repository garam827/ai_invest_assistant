"""Daily recommendations, report publication, static export, and notifications."""
from __future__ import annotations

import logging

from invest_assistant import config
from invest_assistant import universe as instrument_universe
from invest_assistant.data import market as data_fetcher
from invest_assistant.portfolio import paper as paper_trading
from invest_assistant.publishing import static as static_export
from invest_assistant.publishing import telegram as telegram_notifier
from invest_assistant.recommendations import briefing as llm_briefing
from invest_assistant.recommendations.engine import (
    BACKTEST_SUMMARY_FILENAME,
    RECOMMENDATIONS_FILENAME_PREFIX,
    SIGNAL_HISTORY_FILENAME,
    _actions_from_results,
    _recent_signal_history,
    _resolve_report_date,
    get_macro_issues_briefing,
    get_recommendation_for_ticker,
    get_sp500_signal_summary,
    load_signal_history,
)
from invest_assistant.reporting import report as report_builder
from invest_assistant.storage import reports as report_store
from invest_assistant.storage.drive import DriveDB

logger = logging.getLogger(__name__)

def run_asset_class_recommendations(
    drive_db: DriveDB, tickers: dict | None = None, as_of: str | None = None
) -> dict:
    """Run get_recommendation_for_ticker for each representative asset-class ticker
    (instrument_universe.ASSET_CLASS_TICKERS by default — NOT the full S&P 500 universe), and
    persist the day's results to Drive as `_recommendations_{date}.json` (or
    `_recommendations_{date}_test.json` when config.IS_TEST_REPORT is set — see below).

    `as_of` (YYYY-MM-DD, inclusive): backfill a historical report as of this trading day
    instead of every ticker's true latest bar -- threaded through to
    get_recommendation_for_ticker/get_sp500_signal_summary, and used directly as the report
    date (skipping _resolve_report_date's SPY-anchored inference, since the caller already
    knows exactly which day this is). For recovering a specific lost/mislabeled past day
    (see _resolve_report_date) -- the normal daily cron never sets this.
    """
    tickers = tickers if tickers is not None else instrument_universe.ASSET_CLASS_TICKERS
    logger.info("Starting asset-class recommendations for %d tickers", len(tickers))

    results: dict[str, dict] = {}
    for ticker in tickers:
        try:
            reco = get_recommendation_for_ticker(drive_db, ticker, as_of=as_of)
            if reco is None:
                logger.warning("No data (or stale data) for %s, skipping recommendation", ticker)
                continue
            results[ticker] = reco
            logger.info("%s -> 추천: %s", ticker, reco["action"])
        except Exception:
            logger.exception("Failed to generate recommendation for %s", ticker)

    missing = set(tickers) - set(results)
    if missing:
        raise RuntimeError(
            f"Incomplete recommendations; refusing to publish: {', '.join(sorted(missing))}"
        )
    date = as_of if as_of is not None else _resolve_report_date(results)
    # A manual/sample publish (config.IS_TEST_REPORT) gets its own filename via a "_test"
    # suffix — applied to both the recommendations JSON and the report below — so re-running
    # the workflow to check the pipeline/report/Telegram plumbing can't clobber that day's
    # real recommendations archive or report.
    file_date = f"{date}_test" if config.IS_TEST_REPORT else date

    try:
        drive_db.save_json(f"{RECOMMENDATIONS_FILENAME_PREFIX}{file_date}.json", results)
        logger.info("Saved %d recommendations to _recommendations_%s.json", len(results), file_date)
    except Exception:
        # Don't let a transient Drive/network failure on the final save discard the
        # per-ticker work already done — the caller still gets the in-memory results.
        logger.exception("Failed to persist recommendations to Drive (results still returned)")

    # Update the signal-history accumulator (see SIGNAL_HISTORY_FILENAME above) — real
    # publishes only, so a manual/sample test run never pollutes this persistent history.
    if results and not config.IS_TEST_REPORT:
        try:
            history = load_signal_history(drive_db)
            history[date] = _actions_from_results(results)
            drive_db.save_json(SIGNAL_HISTORY_FILENAME, history)
        except Exception:
            logger.exception("Failed to update signal history (recommendations/report/Telegram unaffected)")

    report_date = file_date

    # Paper trading (모의 투자) positions — recorded only via the Streamlit UI, never by this
    # cron path — are read-only here so the day's report/Telegram summary can include them.
    # A failure here must never block the recommendations/report/Telegram that already
    # succeeded (same principle as every other try/except in this function).
    try:
        open_positions = [
            p
            for p in paper_trading.compute_position_returns(drive_db, paper_trading.load_positions(drive_db))
            if p["status"] == "open"
        ]
    except Exception:
        logger.exception("Failed to load paper trading positions (report/Telegram will omit this section)")
        open_positions = []

    # Recent signal history (최근 20거래일) for the report's own reference table — Drive-only,
    # never reaches the LLM/news calls above. A failure here must not block the report either.
    try:
        history_for_table = load_signal_history(drive_db)
        if as_of is not None:
            # Don't let the embedded "recent history" table leak dates *after* the day this
            # backfilled report claims to represent.
            history_for_table = {d: v for d, v in history_for_table.items() if d <= as_of}
        recent_history = _recent_signal_history(history_for_table)
    except Exception:
        logger.exception("Failed to load signal history (report will omit this section)")
        recent_history = {}
        history_for_table = {}

    # S&P 500 mechanical-only signals (user request) — computed fresh every run (cheap, no
    # LLM/news, see get_sp500_signal_summary's docstring), unlike backtest_summary below
    # which is a manual/local artifact this cron only ever reads.
    try:
        sp500_signals = get_sp500_signal_summary(drive_db, as_of=as_of)
    except Exception:
        logger.exception("Failed to compute S&P 500 signal summary (report will omit this section)")
        sp500_signals = []

    # Full-universe backtest summary (backtest.py's `python backtest.py full-universe`,
    # manual/local — see investment_assistant_spec.md [기능 7]) — read-only. Missing/failed
    # load just omits that report section, same as sp500_signals above.
    try:
        backtest_summary = drive_db.load_json(BACKTEST_SUMMARY_FILENAME)
    except Exception:
        logger.exception("Failed to load backtest summary (report will omit this section)")
        backtest_summary = None

    # VIX + short/mid/long US Treasury yield macro-context snapshot (user request) — fetched
    # fresh live via yfinance every run, not stored to Drive/run through signal_engine (see
    # data_fetcher.fetch_macro_snapshot's docstring). A fetch failure just omits the section.
    try:
        macro_snapshot = data_fetcher.fetch_macro_snapshot()
    except Exception:
        logger.exception("Failed to fetch macro snapshot (report will omit this section)")
        macro_snapshot = {}

    # General (non-ticker) 해외 매크로/지정학 이슈 요약 (user request) -- Exa search + LLM
    # distillation, independent of any single ticker's signal. Skipped on a SKIP_LLM_AND_NEWS
    # test run (see get_macro_issues_briefing) and omitted on any other failure, same as every
    # other optional report section above.
    try:
        macro_issues = get_macro_issues_briefing(drive_db)
    except Exception:
        logger.exception("Failed to generate macro issues briefing (report will omit this section)")
        macro_issues = None

    overview = ""
    if results and not config.SKIP_LLM_AND_NEWS:
        try:
            overview = llm_briefing.generate_portfolio_overview(results, recent_history)
        except Exception:
            logger.exception("Failed to generate portfolio overview")

    report_url = None
    if results:
        try:
            report_html = report_builder.build_daily_report_html(
                drive_db,
                results,
                paper_positions=open_positions,
                signal_history=recent_history,
                sp500_signals=sp500_signals,
                backtest_summary=backtest_summary,
                macro_snapshot=macro_snapshot,
                macro_issues=macro_issues,
                overview=overview,
            )
            report_store.save_report(drive_db, report_date, report_html)
            # A test publish now does reach docs/reports/GitHub Pages too (v3.52, under its
            # own "_test"-suffixed URL — see report_store.save_report), but Telegram still
            # only gets a link for a real publish — a test run's whole point is to check the
            # pipeline without also sending a live-looking notification.
            if not config.IS_TEST_REPORT:
                report_url = f"{config.REPORT_BASE_URL}/{report_date}.html"
            logger.info("Saved daily report for %s", report_date)
        except Exception:
            # A failed report build must never take down the recommendation batch or the
            # Telegram summary — same "never drop what already succeeded" principle as the
            # per-ticker LLM/news fallback above.
            logger.exception("Failed to build/save the daily report (results still returned)")

    # Static JSON export for the read-only React site (web/, published to docs/data/ via
    # GitHub Pages) -- overwritten every run, independent of the HTML report above. A
    # failure here must never take down the report/Telegram summary that already succeeded,
    # same principle as every other optional step in this function. No-ops entirely on a
    # manual/sample (config.IS_TEST_REPORT) run, same as report_url above -- and likewise
    # skipped entirely for an `as_of` historical backfill, since docs/data/*.json is always
    # meant to reflect the *current* latest snapshot; overwriting it with a past date's
    # (deliberately stale, possibly HOLD-heavy) results would regress the live site.
    if as_of is None:
        try:
            static_export.export_signals_json(results, sp500_signals, signal_history=recent_history, overview=overview)
            static_export.export_universe_json(drive_db)
            static_export.export_chart_data(drive_db)
            static_export.export_reports_index(history_for_table)
        except Exception:
            logger.exception("Failed to export static JSON for the React site (report/Telegram unaffected)")

    # Skipped for an `as_of` historical backfill -- a Telegram message reading like "today's"
    # summary for a day that's actually several days in the past would just be confusing.
    if as_of is None and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            telegram_notifier.notify_recommendations(results, report_url=report_url, paper_positions=open_positions)
        except Exception:
            logger.exception("Failed to send Telegram notifications (results still returned)")
    elif as_of is None:
        logger.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set, skipping Telegram notification")

    return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_asset_class_recommendations(DriveDB())

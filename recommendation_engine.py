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
import time

import pandas as pd

import config
import data_fetcher
import news_fetcher
import openrouter_briefing
import paper_trading
import report_builder
import signal_engine
import telegram_notifier
from drive_db import DriveDB

logger = logging.getLogger(__name__)

RECOMMENDATIONS_FILENAME_PREFIX = "_recommendations_"

# Lightweight {date: {ticker: action}} accumulator — one small file, vs. re-reading every
# day's full _recommendations_{date}.json (which also carries LLM text/news, unused by
# anything that just wants "what was the action that day") for the Streamlit report-history
# table's per-ticker action columns. Real dates only — see run_asset_class_recommendations.
SIGNAL_HISTORY_FILENAME = "_signal_history.json"


def load_signal_history(drive_db: DriveDB) -> dict:
    return drive_db.load_json(SIGNAL_HISTORY_FILENAME) or {}


def _recent_signal_history(history: dict, days: int = 30) -> dict:
    """Slice to the last `days` calendar days — used for the daily report's embedded signal
    history table (report_builder._build_signal_history_html), which shouldn't grow forever
    the way the Streamlit report-history tab's full-history view does."""
    cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).date().isoformat()
    return {date: actions for date, actions in history.items() if date >= cutoff}


def _actions_from_results(results: dict) -> dict[str, str]:
    return {ticker: reco["action"] for ticker, reco in results.items()}


def _signal_history_for_ticker(raw_df: pd.DataFrame) -> dict[str, str]:
    """date -> mechanical action for one ticker's OHLCV (signal_engine.compute_signals +
    get_mechanical_action). Shared by backfill_signal_history_from_prices (Drive-sourced,
    limited to whatever's in the 5y rolling snapshot) and backfill_signal_history_deep
    (yfinance-sourced, as deep as requested) so the per-row logic isn't duplicated."""
    signals = signal_engine.compute_signals(raw_df)
    result: dict[str, str] = {}
    for _, row in signals.iterrows():
        date = pd.Timestamp(row["Date"]).strftime("%Y-%m-%d")
        summary = {
            "breakout_20": bool(row["Breakout_20"]),
            "breakout_100": bool(row["Breakout_100"]),
            "exit_signal": bool(row["Exit_Signal"]),
        }
        result[date] = signal_engine.get_mechanical_action(summary)
    return result


def backfill_signal_history_from_prices(drive_db: DriveDB, tickers: dict | None = None) -> dict:
    """Full historical rebuild of _signal_history.json computed directly from each ticker's
    stored OHLCV — much deeper than backfill_signal_history below, which is limited to
    whatever _recommendations_{date}.json files already exist (i.e. only since the cron
    started actually running), but still capped by Drive's 5-year rolling snapshot. See
    backfill_signal_history_deep for a rebuild that isn't even limited by that. Purely
    mechanical, no network calls, safe to re-run (always a full rebuild).
    """
    tickers = tickers if tickers is not None else data_fetcher.ASSET_CLASS_TICKERS
    history: dict[str, dict[str, str]] = {}
    for ticker in tickers:
        raw_df = drive_db.load_ticker(ticker)
        if raw_df is None or raw_df.empty:
            continue
        for date, action in _signal_history_for_ticker(raw_df).items():
            history.setdefault(date, {})[ticker] = action
    drive_db.save_json(SIGNAL_HISTORY_FILENAME, history)
    return history


def backfill_signal_history_deep(
    drive_db: DriveDB, start: str = "2007-01-01", tickers: dict | None = None
) -> dict:
    """The deepest signal-history rebuild — fetches full OHLCV directly from yfinance
    (data_fetcher.fetch_ohlcv, start=`start`) instead of Drive's 5-year rolling snapshot, so
    coverage isn't capped by the production Parquet retention window. Doesn't touch Drive's
    per-ticker OHLCV storage at all (computed in memory; only the resulting
    {date: {ticker: action}} accumulator is saved) — this is a manual/occasional research
    operation, not part of the daily cron, so it makes real yfinance calls (throttled via
    config.YFINANCE_REQUEST_DELAY_SEC like every other bulk fetch in this codebase).
    2007-01-01 default covers 11 of the 12 ASSET_CLASS_TICKERS in full; only BTC-USD (from
    2014-09-17) is shorter no matter the start date used here, since yfinance simply has no
    earlier data for it (CPER, the previous 2011-11-15 straggler, was replaced by DBB in
    v3.38 specifically because DBB starts 2007-01-05, closing that gap).
    """
    tickers = tickers if tickers is not None else data_fetcher.ASSET_CLASS_TICKERS
    history: dict[str, dict[str, str]] = {}
    for ticker in tickers:
        raw_df = data_fetcher.fetch_ohlcv(ticker, start=start)
        if raw_df.empty:
            logger.warning("No data returned for %s from %s, skipping", ticker, start)
            continue
        for date, action in _signal_history_for_ticker(raw_df).items():
            history.setdefault(date, {})[ticker] = action
        time.sleep(config.YFINANCE_REQUEST_DELAY_SEC)
    drive_db.save_json(SIGNAL_HISTORY_FILENAME, history)
    return history


def backfill_signal_history(drive_db: DriveDB) -> dict:
    """Rebuild _signal_history.json from every existing _recommendations_{date}.json in
    Drive (re-run-safe — always a full rebuild, not an incremental append). Test-suffixed
    dates are excluded, same as report_builder.list_report_dates. Only covers the (short)
    window _recommendations_*.json files already exist for — see
    backfill_signal_history_from_prices above for a much deeper, price-derived rebuild."""
    filenames = drive_db.list_filenames(RECOMMENDATIONS_FILENAME_PREFIX)
    history: dict[str, dict[str, str]] = {}
    for filename in filenames:
        date = filename.removeprefix(RECOMMENDATIONS_FILENAME_PREFIX).removesuffix(".json")
        if date.endswith("_test"):
            continue
        results = drive_db.load_json(filename)
        if results:
            history[date] = _actions_from_results(results)
    drive_db.save_json(SIGNAL_HISTORY_FILENAME, history)
    return history


def _is_data_fresh(raw_df: pd.DataFrame, max_age_days: int = config.DATA_FRESHNESS_MAX_AGE_DAYS) -> bool:
    """True if the most recent stored bar is within max_age_days of now.

    Guards against generating a recommendation from stale data when collection silently
    failed for one ticker (data_fetcher logs and skips per-ticker errors rather than
    failing the whole run, so a green workflow run doesn't guarantee every ticker updated).
    """
    last_date = pd.to_datetime(raw_df["Date"]).max()
    age_days = (pd.Timestamp.now(tz="UTC").tz_localize(None) - last_date).days
    return age_days <= max_age_days


def _format_ichimoku_note(ichimoku_confluence: dict | None) -> str | None:
    """Advisory-only sentence describing whether today's Ichimoku cloud position agrees
    with the mechanical action — never changes the action or suggested_shares, see
    signal_engine.get_ichimoku_confluence."""
    if ichimoku_confluence is None:
        return None
    position_kr = {"above": "구름 위", "below": "구름 아래", "inside": "구름 안"}[ichimoku_confluence["position"]]
    cloud_kr = "양운(상승 구름)" if ichimoku_confluence["cloud_bullish"] else "음운(하락 구름)"
    if ichimoku_confluence["agrees_with_action"]:
        return f"일목균형표 상으로도 {position_kr}·{cloud_kr}로 추세와 일치합니다."
    return f"다만 일목균형표 상으로는 {position_kr}·{cloud_kr} 상태로 추세와 엇갈려, 비중을 줄여 진입하는 것도 고려해볼 만합니다."


def _build_rule_based_explanation(
    ticker: str,
    action: str,
    summary: dict,
    news: list[dict] | None = None,
    reason: str = "failed",
    ichimoku_confluence: dict | None = None,
) -> str:
    """Deterministic fallback explanation when the LLM isn't used — cites the exact numeric
    rule that fired, so a 매수/매도 call is never sent with no reasoning at all.

    `reason` distinguishes an actual failure ("failed": LLM/news call errored) from an
    intentional skip ("disabled": config.SKIP_LLM_AND_NEWS or use_llm=False), just for the
    header wording — the rest of the explanation is identical either way.
    """
    header = "[규칙 기반 자동 생성 — LLM 분석 실패로 대체]" if reason == "failed" else "[규칙 기반 자동 생성 — LLM 분석 비활성화]"
    lines = [header]
    if action == "매수":
        window = "20일" if summary["breakout_20"] else "100일"
        lines.append(f"종가 {summary['close']:.2f}가 {window} Donchian 채널 상단을 상향 돌파해 매수 시그널이 발생했습니다.")
    else:  # 매도
        lines.append(
            f"종가 {summary['close']:.2f}가 트레일링 스탑 {summary['trailing_stop']:.2f} 아래로 하향 이탈해 "
            f"청산(매도) 시그널이 발생했습니다."
        )
    lines.append(
        f"ATR(14일): {summary['atr']:.2f} · 트레일링 스탑: {summary['trailing_stop']:.2f} · "
        f"거래량 급증: {'예' if summary['volume_surge'] else '아니오'}"
    )
    ichimoku_note = _format_ichimoku_note(ichimoku_confluence)
    if ichimoku_note:
        lines.append(ichimoku_note)
    if news:
        note = "LLM 분석이 실패해 요약은 생략됨" if reason == "failed" else "LLM 분석은 비활성화되어 요약은 생략됨"
        lines.append(f"(참고: 관련 뉴스 {len(news)}건은 수집됐으나 {note})")
    return "\n".join(lines)


def get_recommendation_for_ticker(drive_db: DriveDB, ticker: str, use_llm: bool = True) -> dict | None:
    """Get a 매수/HOLD/매도 call for one ticker.

    The action itself always comes from signal_engine.get_mechanical_action — deterministic,
    no network call — and is NEVER dropped due to a news/LLM failure: on a 매수/매도 day we
    try to fetch news (Exa) and ask the LLM for a narrative explanation, but if either call
    fails (rate limit, outage, etc.) we fall back to a rule-based explanation instead of
    losing the recommendation entirely. The LLM's own parsed action is logged if it disagrees
    with the mechanical one, but never overrides it.

    `use_llm=False` (e.g. app.py's public-deployment mode, config.STREAMLIT_ENABLE_LLM) still
    collects news but skips the OpenRouter call entirely, going straight to the rule-based
    explanation — distinct from config.SKIP_LLM_AND_NEWS below, which skips news too.

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

    ichimoku_confluence = signal_engine.get_ichimoku_confluence(summary, action)

    news: list[dict] = []
    if config.SKIP_LLM_AND_NEWS:
        logger.info("%s: SKIP_LLM_AND_NEWS set, using rule-based explanation without calling Exa/OpenRouter", ticker)
        text = _build_rule_based_explanation(
            ticker, action, summary, news, reason="disabled", ichimoku_confluence=ichimoku_confluence
        )
        return {
            "ticker": ticker,
            "action": action,
            "text": text,
            "news": news,
            "close": summary["close"],
            "date": str(summary["date"]),
        }

    try:
        # Read-through cache first — same ticker/date requested by another user (or an
        # earlier run today) reuses the archived result instead of paying for Exa again.
        news = news_fetcher.get_cached_news(drive_db, ticker)
        if news is None:
            # ASSET_CLASS_TICKERS' proxies (e.g. GLD for gold) search under the underlying
            # asset's name via news_query instead of the ticker itself — "GLD stock news"
            # mostly surfaces "GLD down X%" wire blurbs, not the macro drivers behind the move.
            news_query = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {}).get("news_query")
            news = news_fetcher.fetch_ticker_news_exa(ticker, query=news_query)
            news_fetcher.archive_news(drive_db, ticker, news)
    except Exception:
        logger.exception("%s: news fetch failed, proceeding without it", ticker)
        news = []

    if not use_llm:
        text = _build_rule_based_explanation(
            ticker, action, summary, news, reason="disabled", ichimoku_confluence=ichimoku_confluence
        )
        return {
            "ticker": ticker,
            "action": action,
            "text": text,
            "news": news,
            "close": summary["close"],
            "date": str(summary["date"]),
        }

    try:
        reco = openrouter_briefing.generate_recommendation(
            ticker, news, summary, ichimoku_confluence=ichimoku_confluence
        )
        if reco["action"] != action:
            logger.warning(
                "%s: LLM action (%s) disagreed with mechanical rule (%s) — using the mechanical one",
                ticker,
                reco["action"],
                action,
            )
        text = reco["text"]
    except Exception:
        logger.exception("%s: LLM call failed for a %s signal — falling back to rule-based explanation", ticker, action)
        text = _build_rule_based_explanation(ticker, action, summary, news, ichimoku_confluence=ichimoku_confluence)

    return {
        "ticker": ticker,
        "action": action,
        "text": text,
        "news": news,
        "close": summary["close"],
        "date": str(summary["date"]),
    }


def run_asset_class_recommendations(drive_db: DriveDB, tickers: dict | None = None) -> dict:
    """Run get_recommendation_for_ticker for each representative asset-class ticker
    (data_fetcher.ASSET_CLASS_TICKERS by default — NOT the full S&P 500 universe), and
    persist the day's results to Drive as `_recommendations_{date}.json` (or
    `_recommendations_{date}_test.json` when config.IS_TEST_REPORT is set — see below).
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

    # Recent signal history (최근 30일) for the report's own reference table — Drive-only,
    # never reaches the LLM/news calls above. A failure here must not block the report either.
    try:
        recent_history = _recent_signal_history(load_signal_history(drive_db))
    except Exception:
        logger.exception("Failed to load signal history (report will omit this section)")
        recent_history = {}

    report_url = None
    if results:
        try:
            report_html = report_builder.build_daily_report_html(
                drive_db, results, paper_positions=open_positions, signal_history=recent_history
            )
            report_builder.save_report(drive_db, report_date, report_html)
            # A test publish is never committed to docs/reports (see report_builder.save_report),
            # so it never actually reaches GitHub Pages — don't hand out a URL that 404s.
            if not config.IS_TEST_REPORT:
                report_url = f"{config.REPORT_BASE_URL}/{report_date}.html"
            logger.info("Saved daily report for %s", report_date)
        except Exception:
            # A failed report build must never take down the recommendation batch or the
            # Telegram summary — same "never drop what already succeeded" principle as the
            # per-ticker LLM/news fallback above.
            logger.exception("Failed to build/save the daily report (results still returned)")

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            telegram_notifier.notify_recommendations(results, report_url=report_url, paper_positions=open_positions)
        except Exception:
            logger.exception("Failed to send Telegram notifications (results still returned)")
    else:
        logger.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set, skipping Telegram notification")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_asset_class_recommendations(DriveDB())

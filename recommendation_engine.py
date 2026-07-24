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
import paper_trading
import report_builder
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

    report_url = None
    if results:
        try:
            report_html = report_builder.build_daily_report_html(drive_db, results, paper_positions=open_positions)
            report_builder.save_report(drive_db, report_date, report_html)
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

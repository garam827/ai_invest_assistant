"""Telegram notifications for the daily asset-class recommendation cron run.

Only called from recommendation_engine.run_asset_class_recommendations (the batch/cron
path) — never from the interactive Streamlit UI's single-ticker get_recommendation, or
every "조회" click in the app would spam the chat.
"""
from __future__ import annotations

import logging

import requests

import chart_builder
import config
import signal_engine
from drive_db import DriveDB

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
ACTION_EMOJI = {"매수": "🟢", "HOLD": "⚪", "매도": "🔴"}


def _require_config() -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise ValueError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is not set")


def send_message(text: str) -> None:
    _require_config()
    url = f"{TELEGRAM_API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
        timeout=30,
    )
    response.raise_for_status()


def send_photo(image_bytes: bytes, caption: str = "") -> None:
    _require_config()
    url = f"{TELEGRAM_API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)}/sendPhoto"
    response = requests.post(
        url,
        data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1024]},
        files={"photo": ("chart.png", image_bytes, "image/png")},
        timeout=60,
    )
    response.raise_for_status()


def format_summary(results: dict) -> str:
    date = next(iter(results.values()))["date"] if results else ""
    lines = [f"*톰 바소 추세추종 일일 리포트* ({date})", ""]
    for ticker, reco in results.items():
        emoji = ACTION_EMOJI.get(reco["action"], "⚪")
        lines.append(f"{emoji} `{ticker}` — *{reco['action']}*  (종가 {reco['close']:.2f})")
    return "\n".join(lines)


def notify_recommendations(drive_db: DriveDB, results: dict) -> None:
    """Send the daily text summary (all tickers), then a chart image for each 매수/매도
    ticker only — HOLD days don't get a chart, to keep the daily message count reasonable.
    """
    if not results:
        logger.info("No recommendations to notify")
        return

    try:
        send_message(format_summary(results))
    except Exception:
        logger.exception("Failed to send Telegram summary message")

    signal_tickers = [ticker for ticker, reco in results.items() if reco["action"] in ("매수", "매도")]
    for ticker in signal_tickers:
        try:
            raw_df = drive_db.load_ticker(ticker)
            view = signal_engine.compute_signals(raw_df)
            fig = chart_builder.build_ticker_chart_figure(ticker, view)
            image_bytes = fig.to_image(format="png", width=1400, height=1000, scale=2)
            send_photo(image_bytes, caption=f"{ticker} — {results[ticker]['action']}")
        except Exception:
            logger.exception("Failed to send Telegram chart for %s", ticker)

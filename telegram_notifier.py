"""Telegram notifications for the daily asset-class recommendation cron run.

Only called from recommendation_engine.run_asset_class_recommendations (the batch/cron
path) — never from the interactive Streamlit UI's single-ticker get_recommendation, or
every "조회" click in the app would spam the chat.
"""
from __future__ import annotations

import logging
import unicodedata

import requests

import chart_builder
import config
import data_fetcher
import signal_engine
from drive_db import DriveDB

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
ACTION_EMOJI = {"매수": "🟢", "HOLD": "⚪", "매도": "🔴"}
CHART_PERIOD_DAYS = 180  # 6개월 — 전체 히스토리(수년치)를 다 넣으면 이미지 한 장에서 캔들이 안 보일 정도로 눌려버림


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


def _display_width(text: str) -> int:
    """Monospace 표 정렬을 위한 시각적 폭 — 한글 등 동아시아 전각 문자는 2칸으로 계산한다
    (파이썬 len()은 이런 문자도 1로 세어, 영문/한글이 섞인 열은 그대로 두면 정렬이 깨진다)."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def format_summary(results: dict) -> str:
    """Telegram 봇 메시지는 HTML <table>을 지원하지 않으므로, 마크다운 코드블록(등폭 서체)
    안에 컬럼을 정렬해 표처럼 보이게 만든다. 이모지는 클라이언트마다 표시 폭이 달라 표 안에
    섞으면 정렬이 어긋날 수 있어 상단 범례로만 쓰고, 행 안의 액션은 순수 텍스트로 둔다.
    """
    date = next(iter(results.values()))["date"] if results else ""

    headers = ["티커", "구분", "액션", "종가"]
    rows = []
    for ticker, reco in results.items():
        category = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {}).get("category", "")
        rows.append([ticker, category, reco["action"], f"{reco['close']:.2f}"])

    col_widths = [
        max([_display_width(headers[i])] + [_display_width(row[i]) for row in rows]) for i in range(len(headers))
    ]

    def _format_row(cells: list[str]) -> str:
        return "  ".join(_pad(cell, col_widths[i]) for i, cell in enumerate(cells))

    table_lines = [_format_row(headers), "  ".join("-" * w for w in col_widths)]
    table_lines.extend(_format_row(row) for row in rows)

    legend = "  ".join(f"{emoji} {action}" for action, emoji in ACTION_EMOJI.items())
    return (
        f"*톰 바소 추세추종 일일 리포트* ({date})\n"
        f"{legend}\n"
        "```\n" + "\n".join(table_lines) + "\n```"
    )


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
            signals = signal_engine.compute_signals(raw_df)
            view = chart_builder.slice_to_period(signals, CHART_PERIOD_DAYS)
            fig = chart_builder.build_ticker_chart_figure(ticker, view)
            image_bytes = fig.to_image(format="png", width=1400, height=1000, scale=2)
            description = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {}).get("description", "")
            caption = f"{ticker} — {results[ticker]['action']}"
            if description:
                caption += f"\n{description}"
            send_photo(image_bytes, caption=caption)
        except Exception:
            logger.exception("Failed to send Telegram chart for %s", ticker)

"""Combined daily HTML report across all ASSET_CLASS_TICKERS — one page with an LLM
cross-asset overview, a signal summary table, and per-ticker candlestick charts.

Persisted to Drive as REPORT_FILENAME_PREFIX + {date}.html (so the Streamlit report-history
tab can re-render past days without recomputation) and written to a local docs/reports/
file so recommend.yml can commit+push it for GitHub Pages to serve publicly — that public
URL is what telegram_notifier links to instead of attaching every chart individually.
"""
from __future__ import annotations

import datetime
import os

import chart_builder
import data_fetcher
import openrouter_briefing
import signal_engine

REPORT_FILENAME_PREFIX = "_report_"
LOCAL_REPORT_DIR = os.path.join("docs", "reports")
CHART_PERIOD_DAYS = 180  # 6개월 — telegram_notifier와 동일한 표시 구간

ACTION_COLOR = {"매수": "#2e7d32", "HOLD": "#757575", "매도": "#c62828"}


def _build_summary_table_html(results: dict) -> str:
    rows = []
    for ticker, reco in results.items():
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        color = ACTION_COLOR.get(reco["action"], "#757575")
        rows.append(
            "<tr>"
            f"<td>{ticker}</td>"
            f"<td>{meta.get('label', '')}</td>"
            f"<td>{meta.get('category', '')}</td>"
            f"<td style='color:{color};font-weight:bold'>{reco['action']}</td>"
            f"<td>{reco['close']:.2f}</td>"
            "</tr>"
        )
    return (
        "<table class='summary'><thead><tr>"
        "<th>티커</th><th>자산</th><th>구분</th><th>액션</th><th>종가</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _build_chart_sections_html(drive_db, results: dict) -> str:
    sections = []
    first = True
    for ticker in results:
        try:
            raw_df = drive_db.load_ticker(ticker)
            if raw_df is None or raw_df.empty:
                continue
            signals = signal_engine.compute_signals(raw_df)
            view = chart_builder.slice_to_period(signals, CHART_PERIOD_DAYS)
            fig = chart_builder.build_ticker_chart_figure(ticker, view)
            chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn" if first else False)
            first = False
        except Exception:
            continue
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        sections.append(f"<h2>{ticker} — {meta.get('label', '')}</h2>{chart_html}")
    return "".join(sections)


def build_daily_report_html(drive_db, results: dict) -> str:
    """Build the full standalone HTML report page for one day's recommendation results."""
    date = next(iter(results.values()))["date"] if results else datetime.date.today().isoformat()

    try:
        overview = openrouter_briefing.generate_portfolio_overview(results)
    except Exception:
        overview = ""

    overview_html = f"<p class='overview'>{overview}</p>" if overview else ""
    table_html = _build_summary_table_html(results)
    charts_html = _build_chart_sections_html(drive_db, results)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>톰 바소 추세추종 일일 리포트 ({date})</title>
<style>
  body {{ font-family: "Malgun Gothic", "Nanum Gothic", "Noto Sans CJK KR", sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; color: #212121; }}
  table.summary {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
  table.summary th, table.summary td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: center; }}
  table.summary th {{ background: #f5f5f5; }}
  .overview {{ background: #f9f9f9; border-left: 4px solid #546e7a; padding: 1rem; line-height: 1.6; margin: 1rem 0 2rem; }}
</style>
</head>
<body>
<h1>톰 바소 추세추종 일일 리포트 ({date})</h1>
{overview_html}
{table_html}
{charts_html}
</body>
</html>"""


def save_report(drive_db, date: str, html: str) -> None:
    """Persist the report both to Drive (for the Streamlit history tab) and to a local
    docs/reports/ file (for recommend.yml to commit+push so GitHub Pages serves it).
    """
    drive_db.save_text(f"{REPORT_FILENAME_PREFIX}{date}.html", html)

    os.makedirs(LOCAL_REPORT_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_REPORT_DIR, f"{date}.html"), "w", encoding="utf-8") as f:
        f.write(html)


def list_report_dates(drive_db) -> list[str]:
    """Dates (YYYY-MM-DD, newest first) with a saved report in Drive."""
    filenames = drive_db.list_filenames(REPORT_FILENAME_PREFIX)
    dates = [f.removeprefix(REPORT_FILENAME_PREFIX).removesuffix(".html") for f in filenames]
    return sorted(dates, reverse=True)


def load_report(drive_db, date: str) -> str | None:
    return drive_db.load_text(f"{REPORT_FILENAME_PREFIX}{date}.html")

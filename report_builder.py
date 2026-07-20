"""Combined daily HTML report across all ASSET_CLASS_TICKERS — one page with an LLM
cross-asset overview, a signal summary table, per-ticker news + LLM analysis for 매수/매도
tickers (reusing recommendation_engine's already-collected Exa news + narrative — no
separate news fetch here), and collapsible candlestick charts for every ticker.

Persisted to Drive as REPORT_FILENAME_PREFIX + {date}.html (so the Streamlit report-history
tab can re-render past days without recomputation) and written to a local docs/reports/
file so recommend.yml can commit+push it for GitHub Pages to serve publicly — that public
URL is what telegram_notifier links to instead of attaching every chart individually.
"""
from __future__ import annotations

import datetime
import html
import os

import chart_builder
import config
import data_fetcher
import openrouter_briefing
import signal_engine

REPORT_FILENAME_PREFIX = "_report_"
LOCAL_REPORT_DIR = os.path.join("docs", "reports")
CHART_PERIOD_DAYS = 180  # 6개월 — telegram_notifier와 동일한 표시 구간
SIGNAL_ACTIONS = ("매수", "매도")

ACTION_COLOR = {"매수": "#2e7d32", "HOLD": "#757575", "매도": "#c62828"}
ACTION_CLASS = {"매수": "buy", "HOLD": "hold", "매도": "sell"}

STYLE = """
  * { box-sizing: border-box; }
  body { font-family: "Malgun Gothic", "Nanum Gothic", "Noto Sans CJK KR", sans-serif; width: 97%; max-width: none; margin: 2rem auto; color: #212121; line-height: 1.5; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.2rem; margin-top: 2.5rem; border-bottom: 2px solid #eee; padding-bottom: 0.4rem; }
  /* 본문 문단(총평/분석 텍스트)만 가독성을 위해 읽기 편한 폭으로 제한 — 표·차트·뉴스 그리드는
     제한 없이 컨테이너(위 body) 전체 폭을 그대로 쓴다. */
  .overview { background: #f9f9f9; border-left: 4px solid #546e7a; padding: 1rem; line-height: 1.6; margin: 1rem 0 2rem; max-width: 900px; }
  table.summary { border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }
  table.summary th, table.summary td { border: 1px solid #ddd; padding: 6px 10px; text-align: center; }
  table.summary th { background: #f5f5f5; }
  table.summary a { color: inherit; text-decoration: underline; }
  table.summary tr.category-row td { background: #eceff1; font-weight: bold; text-align: left; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; color: #fff; font-weight: bold; font-size: 0.85rem; }
  .signal-card { border: 1px solid #ddd; border-left: 5px solid #999; border-radius: 6px; padding: 1rem 1.2rem; margin-bottom: 1.5rem; scroll-margin-top: 1rem; }
  .signal-card.buy { border-left-color: #2e7d32; }
  .signal-card.sell { border-left-color: #c62828; }
  .signal-card-header { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
  .signal-card-header .ticker { font-size: 1.15rem; font-weight: bold; }
  .signal-card-header .label { color: #666; }
  .signal-card-header .close { margin-left: auto; color: #666; font-size: 0.9rem; }
  .analysis { white-space: pre-wrap; background: #fafafa; border-radius: 6px; padding: 0.8rem 1rem; margin: 0.6rem 0; max-width: 900px; }
  details { margin: 0.8rem 0; }
  details > summary { cursor: pointer; font-weight: bold; padding: 0.5rem 0.8rem; background: #f0f0f0; border-radius: 6px; }
  details[open] > summary { border-radius: 6px 6px 0 0; }
  .news-list h4 { margin-bottom: 0.5rem; }
  .news-cards-grid { display: flex; flex-direction: column; gap: 0.5rem; }
  .news-card { border: 1px solid #eee; border-radius: 6px; padding: 0.5rem 0.8rem; font-size: 0.88rem; width: 100%; }
  .news-card a { font-weight: bold; color: #1a237e; text-decoration: none; }
  .news-card a:hover { text-decoration: underline; }
  .news-card p { margin: 0.3rem 0 0; }
  .news-meta { color: #888; font-size: 0.8rem; margin: 0.2rem 0; }
  .hold-chart-block { margin-bottom: 2rem; }
  .hold-chart-block h4 { margin-bottom: 0.3rem; }
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _build_summary_table_html(results: dict) -> str:
    """results.items()는 ASSET_CLASS_TICKERS 정의 순서를 그대로 따르므로(dict는 삽입 순서 보존),
    같은 카테고리 종목이 이미 연속으로 붙어 있다 — 그 경계마다 그룹 헤더 행을 끼워 넣기만 하면
    별도 정렬 없이 카테고리별로 묶어 보여줄 수 있다.
    """
    rows = []
    last_category = None
    for ticker, reco in results.items():
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        category = meta.get("category", "")
        if category != last_category:
            rows.append(f"<tr class='category-row'><td colspan='4'>{_esc(category)}</td></tr>")
            last_category = category
        color = ACTION_COLOR.get(reco["action"], "#757575")
        ticker_cell = f"<a href='#ticker-{ticker}'>{ticker}</a>" if reco["action"] in SIGNAL_ACTIONS else ticker
        rows.append(
            "<tr>"
            f"<td>{ticker_cell}</td>"
            f"<td>{_esc(meta.get('label', ''))}</td>"
            f"<td style='color:{color};font-weight:bold'>{reco['action']}</td>"
            f"<td>{reco['close']:.2f}</td>"
            "</tr>"
        )
    return (
        "<table class='summary'><thead><tr>"
        "<th>티커</th><th>자산</th><th>액션</th><th>종가</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _build_chart_html(drive_db, ticker: str, include_plotlyjs) -> str | None:
    raw_df = drive_db.load_ticker(ticker)
    if raw_df is None or raw_df.empty:
        return None
    signals = signal_engine.compute_signals(raw_df)
    view = chart_builder.slice_to_period(signals, CHART_PERIOD_DAYS)
    fig = chart_builder.build_ticker_chart_figure(ticker, view)
    return fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs)


def _build_news_cards_html(news_items: list[dict]) -> str:
    if not news_items:
        return ""
    cards = []
    for item in news_items:
        title = _esc(item.get("title", ""))
        link = item.get("link", "")
        meta = " · ".join(filter(None, [_esc(item.get("publisher", "")), _esc(item.get("published_at", ""))]))
        summary = _esc(item.get("summary", ""))
        title_html = f"<a href='{link}' target='_blank' rel='noopener'>{title}</a>" if link else title
        cards.append(
            "<div class='news-card'>"
            f"{title_html}"
            + (f"<div class='news-meta'>{meta}</div>" if meta else "")
            + (f"<p>{summary}</p>" if summary else "")
            + "</div>"
        )
    return f"<div class='news-list'><h4>참고 뉴스 ({len(news_items)}건)</h4><div class='news-cards-grid'>{''.join(cards)}</div></div>"


def _build_signal_sections_html(drive_db, results: dict, chart_js_loaded: list[bool]) -> str:
    """One expandable card per 매수/매도 ticker: LLM narrative (or rule-based fallback text,
    already computed by recommendation_engine.get_recommendation_for_ticker — no news/LLM
    call happens here) + the Exa news articles it was based on + a collapsible chart.
    """
    sections = []
    for ticker, reco in results.items():
        if reco["action"] not in SIGNAL_ACTIONS:
            continue
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        action_class = ACTION_CLASS.get(reco["action"], "hold")
        color = ACTION_COLOR.get(reco["action"], "#757575")

        try:
            chart_html = _build_chart_html(drive_db, ticker, "cdn" if not chart_js_loaded[0] else False)
            chart_js_loaded[0] = True
        except Exception:
            chart_html = None

        chart_block = f"<details><summary>📈 차트 보기 ({CHART_PERIOD_DAYS // 30}개월)</summary>{chart_html}</details>" if chart_html else ""

        sections.append(
            f"<section id='ticker-{ticker}' class='signal-card {action_class}'>"
            "<div class='signal-card-header'>"
            f"<span class='ticker'>{ticker}</span>"
            f"<span class='label'>{_esc(meta.get('label', ''))}</span>"
            f"<span class='badge' style='background:{color}'>{reco['action']}</span>"
            f"<span class='close'>종가 {reco['close']:.2f}</span>"
            "</div>"
            f"<div class='analysis'>{_esc(reco.get('text', ''))}</div>"
            f"{chart_block}"
            f"{_build_news_cards_html(reco.get('news') or [])}"
            "</section>"
        )
    if not sections:
        return "<p>오늘은 매수/매도 시그널이 발생한 종목이 없습니다.</p>"
    return "".join(sections)


def _build_hold_charts_html(drive_db, results: dict, chart_js_loaded: list[bool]) -> str:
    """HOLD tickers get no news/LLM section (recommendation_engine skips both for HOLD) —
    just their chart, tucked into one collapsed block so the page isn't dominated by
    tickers with nothing new to report.
    """
    blocks = []
    for ticker, reco in results.items():
        if reco["action"] in SIGNAL_ACTIONS:
            continue
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        try:
            chart_html = _build_chart_html(drive_db, ticker, "cdn" if not chart_js_loaded[0] else False)
            chart_js_loaded[0] = True
        except Exception:
            continue
        if chart_html is None:
            continue
        blocks.append(f"<div class='hold-chart-block'><h4>{ticker} — {_esc(meta.get('label', ''))} (HOLD)</h4>{chart_html}</div>")
    if not blocks:
        return ""
    return f"<details><summary>📊 HOLD 종목 차트 보기 ({len(blocks)}개, 참고용)</summary>{''.join(blocks)}</details>"


def build_daily_report_html(drive_db, results: dict) -> str:
    """Build the full standalone HTML report page for one day's recommendation results."""
    date = next(iter(results.values()))["date"] if results else datetime.date.today().isoformat()

    overview = ""
    if not config.SKIP_LLM_AND_NEWS:
        try:
            overview = openrouter_briefing.generate_portfolio_overview(results)
        except Exception:
            pass

    overview_html = f"<p class='overview'>{_esc(overview)}</p>" if overview else ""
    table_html = _build_summary_table_html(results)

    chart_js_loaded = [False]  # Plotly CDN <script> only needs to load once across all charts
    signal_html = _build_signal_sections_html(drive_db, results, chart_js_loaded)
    hold_html = _build_hold_charts_html(drive_db, results, chart_js_loaded)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>톰 바소 추세추종 일일 리포트 ({date})</title>
<style>{STYLE}</style>
</head>
<body>
<h1>톰 바소 추세추종 일일 리포트 ({date})</h1>
{overview_html}
{table_html}
<h2>오늘의 매수/매도 시그널</h2>
{signal_html}
{hold_html}
</body>
</html>"""


def save_report(drive_db, date: str, report_html: str) -> None:
    """Persist the report both to Drive (for the Streamlit history tab) and to a local
    docs/reports/ file (for recommend.yml to commit+push so GitHub Pages serves it).
    """
    drive_db.save_text(f"{REPORT_FILENAME_PREFIX}{date}.html", report_html)

    os.makedirs(LOCAL_REPORT_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_REPORT_DIR, f"{date}.html"), "w", encoding="utf-8") as f:
        f.write(report_html)


def list_report_dates(drive_db) -> list[str]:
    """Dates (YYYY-MM-DD, newest first) with a saved report in Drive."""
    filenames = drive_db.list_filenames(REPORT_FILENAME_PREFIX)
    dates = [f.removeprefix(REPORT_FILENAME_PREFIX).removesuffix(".html") for f in filenames]
    return sorted(dates, reverse=True)


def load_report(drive_db, date: str) -> str | None:
    return drive_db.load_text(f"{REPORT_FILENAME_PREFIX}{date}.html")

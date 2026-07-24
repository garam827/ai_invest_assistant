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
  body { font-family: "Malgun Gothic", "Nanum Gothic", "Noto Sans CJK KR", sans-serif; width: 97%; max-width: none; margin: 2rem auto; color: #212121; line-height: 1.5; font-size: 0.92rem; }
  h1 { font-size: 1.5rem; margin: 0; }
  h2 { font-size: 1.2rem; margin-top: 2.5rem; border-bottom: 2px solid #eee; padding-bottom: 0.4rem; }
  .page-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem; }
  .chart-legend-key { font-size: 0.75rem; color: #888; text-align: right; max-width: 340px; line-height: 1.4; }
  .chart-frame { border: 1px solid #ddd; border-radius: 6px; padding: 0.8rem; margin: 0.8rem 0; }
  /* 교차 자산 총평(.overview)만 가독성을 위해 읽기 편한 폭으로 제한 — 표·차트·뉴스 그리드·
     개별 종목 LLM 분석(.analysis)은 제한 없이 컨테이너(위 body) 전체 폭을 그대로 쓴다
     (.analysis는 v3.30까지는 .overview와 같은 900px 제한이 있었으나, 종목별 분석 텍스트가
     상대적으로 좁아 보인다는 피드백으로 v3.30에서 제한을 없앴다). */
  .overview { background: #f9f9f9; border-left: 4px solid #546e7a; padding: 1rem; line-height: 1.6; margin: 1rem 0 2rem; max-width: 900px; }
  table.summary { border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; font-size: 0.8rem; }
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
  .analysis { white-space: pre-wrap; background: #fafafa; border-radius: 6px; padding: 0.8rem 1rem; margin: 0.6rem 0; }
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
  .pnl-positive { color: #2e7d32; font-weight: bold; }
  .pnl-negative { color: #c62828; font-weight: bold; }
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


def _build_paper_trading_html(positions: list[dict]) -> str:
    """positions: open paper-trading positions already enriched by
    paper_trading.compute_position_returns. Empty -> "" (section omitted entirely, no
    news/analysis exists for an empty portfolio any more than it does for a HOLD ticker)."""
    if not positions:
        return ""

    rows = []
    for p in positions:
        if p["current_price"] is None:
            current_cell, pnl_cell = "N/A", "N/A"
        else:
            pnl_class = "pnl-positive" if p["unrealized_pnl"] >= 0 else "pnl-negative"
            current_cell = f"{p['current_price']:.2f}"
            pnl_cell = f"<span class='{pnl_class}'>{p['unrealized_pnl']:+.2f} ({p['unrealized_pnl_pct']:+.2f}%)</span>"
        recorded_date = p["created_at"][:10]  # ISO timestamp -> date only, e.g. "2026-07-23"
        rows.append(
            "<tr>"
            f"<td>{_esc(p['ticker'])}</td>"
            f"<td>{_esc(p['entry_date'])}</td>"
            f"<td>{p['entry_price']:.2f}</td>"
            f"<td>{p['quantity']}</td>"
            f"<td>{_esc(recorded_date)}</td>"
            f"<td>{current_cell}</td>"
            f"<td>{pnl_cell}</td>"
            "</tr>"
        )
    table = (
        "<table class='summary'><thead><tr>"
        "<th>티커</th><th>매수일</th><th>매수가</th><th>수량</th><th>설정일</th><th>현재가</th><th>미실현손익</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    return f"<h2>모의 투자 현황</h2><div class='chart-frame'>{table}</div>"


ACTION_SHORT = {"매수": "B", "HOLD": "H", "매도": "S"}


def _build_signal_history_html(signal_history: dict) -> str:
    """signal_history: {date: {ticker: action}}, already sliced to the desired window by
    the caller (recommendation_engine._recent_signal_history) — this function doesn't do
    its own date math. Empty -> "" (section omitted, same principle as the other optional
    sections above)."""
    if not signal_history:
        return ""

    tickers = list(data_fetcher.ASSET_CLASS_TICKERS)
    dates = sorted(signal_history, reverse=True)
    header = "".join(f"<th>{_esc(t)}</th>" for t in tickers)
    rows = []
    for date in dates:
        day_actions = signal_history[date]
        cells = []
        for ticker in tickers:
            action = day_actions.get(ticker)
            letter = ACTION_SHORT.get(action, "-")
            color = ACTION_COLOR.get(action, "#999")
            cells.append(f"<td style='color:{color};font-weight:bold'>{letter}</td>")
        rows.append(f"<tr><td>{_esc(date)}</td>{''.join(cells)}</tr>")
    table = (
        "<table class='summary'><thead><tr>"
        f"<th>날짜</th>{header}"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    return f"<h2>최근 시그널 이력</h2>{table}"


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

        chart_block = (
            f"<details><summary>📈 차트 보기 ({CHART_PERIOD_DAYS // 30}개월)</summary><div class='chart-frame'>{chart_html}</div></details>"
            if chart_html
            else ""
        )

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
        blocks.append(
            f"<div class='hold-chart-block'><h4>{ticker} — {_esc(meta.get('label', ''))} (HOLD)</h4>"
            f"<div class='chart-frame'>{chart_html}</div></div>"
        )
    if not blocks:
        return ""
    return f"<details><summary>📊 HOLD 종목 차트 보기 ({len(blocks)}개, 참고용)</summary>{''.join(blocks)}</details>"


def build_daily_report_html(
    drive_db,
    results: dict,
    paper_positions: list[dict] | None = None,
    signal_history: dict | None = None,
) -> str:
    """Build the full standalone HTML report page for one day's recommendation results.

    `paper_positions` (paper_trading.compute_position_returns' output, open positions only)
    is optional so existing callers/tests are unaffected — omitted entirely from the report
    if not given or empty (see _build_paper_trading_html).

    `signal_history` ({date: {ticker: action}}, already windowed by the caller — see
    recommendation_engine._recent_signal_history) is likewise optional, omitted if empty
    (see _build_signal_history_html). report_builder.py can't import recommendation_engine
    itself (recommendation_engine already imports report_builder — a back-import would be
    circular), so the caller always loads and passes this in, same as paper_positions.
    """
    date = next(iter(results.values()))["date"] if results else datetime.date.today().isoformat()

    overview = ""
    if not config.SKIP_LLM_AND_NEWS:
        try:
            overview = openrouter_briefing.generate_portfolio_overview(results)
        except Exception:
            pass

    overview_html = f"<p class='overview'>{_esc(overview)}</p>" if overview else ""
    table_html = _build_summary_table_html(results)
    paper_html = _build_paper_trading_html(paper_positions or [])
    history_html = _build_signal_history_html(signal_history or {})

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
<div class="page-header">
<h1>톰 바소 추세추종 일일 리포트 ({date})</h1>
<div class="chart-legend-key">BB=볼린저밴드<br>DC20/DC100=Donchian채널(20일/100일)<br>손절선=트레일링 스탑(고점−3×ATR)<br>양운(붉은색)/음운(파란색)=일목균형표 구름(선행스팬A·B)</div>
</div>
{overview_html}
{table_html}
{history_html}
{paper_html}
<h2>오늘의 매수/매도 시그널</h2>
{signal_html}
{hold_html}
</body>
</html>"""


def save_report(drive_db, date: str, report_html: str) -> None:
    """Persist the report to Drive (for the Streamlit history tab). Also writes a local
    docs/reports/{date}.html file for recommend.yml to commit+push to GitHub Pages — but
    only for a real (non-test) `date`. A "_test"-suffixed date (config.IS_TEST_REPORT) is
    Drive-only, so a manual/sample publish never commits anything to the public repo or
    GitHub Pages — Drive plus the Streamlit "리포트 히스토리" tab's download button is
    enough to inspect a test run's output.
    """
    drive_db.save_text(f"{REPORT_FILENAME_PREFIX}{date}.html", report_html)

    if date.endswith("_test"):
        return

    os.makedirs(LOCAL_REPORT_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_REPORT_DIR, f"{date}.html"), "w", encoding="utf-8") as f:
        f.write(report_html)


def list_report_dates(drive_db) -> list[str]:
    """Dates (YYYY-MM-DD, newest first) with a saved *real* report in Drive — manual/sample
    test publishes (config.IS_TEST_REPORT, "{date}_test") are excluded so the Streamlit
    history list only ever shows genuine daily reports."""
    filenames = drive_db.list_filenames(REPORT_FILENAME_PREFIX)
    dates = [f.removeprefix(REPORT_FILENAME_PREFIX).removesuffix(".html") for f in filenames]
    dates = [d for d in dates if not d.endswith("_test")]
    return sorted(dates, reverse=True)


def load_report(drive_db, date: str) -> str | None:
    return drive_db.load_text(f"{REPORT_FILENAME_PREFIX}{date}.html")

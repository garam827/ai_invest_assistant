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
import json
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
  /* 본문 문단은 표·차트·뉴스 그리드와 마찬가지로 컨테이너(위 body) 전체 폭을 그대로 쓴다.
     원래는 긴 글줄 가독성을 위해 .overview/.analysis 모두 900px로 제한했었으나, 종목별
     분석(.analysis)이 상대적으로 좁아 보인다는 피드백으로 v3.30에서 제한을 없앴고,
     교차 자산 총평(.overview)도 같은 이유로 v3.33에서 제한을 없앴다. */
  .overview { background: #f9f9f9; border-left: 4px solid #546e7a; padding: 1rem; line-height: 1.6; margin: 1rem 0 2rem; }
  /* 정보 밀도가 높은 표(요약/모의투자/시그널 이력/AI 예측) 공통 스타일 -- 한눈에 훑어볼 수 있도록
     행 높이를 낮게 유지한다. 원래 table.summary(패딩 6px 10px)와 table.signal-history(패딩 2px 6px)
     가 서로 다른 밀도로 분리돼 있었으나, 리포트의 모든 표를 동일하게 조밀한 밀도로 맞춰달라는
     요청으로 하나의 table.dense 클래스로 통합했다(v3.44). */
  table.dense { border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; font-size: 0.72rem; }
  table.dense th, table.dense td { border: 1px solid #ddd; padding: 2px 6px; text-align: center; line-height: 1.2; }
  table.dense th { background: #f5f5f5; }
  table.dense a { color: inherit; text-decoration: underline; }
  table.dense tr.category-row td { background: #eceff1; font-weight: bold; text-align: left; }
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
  .prediction-disclaimer { background: #fff8e1; border-left: 4px solid #f9a825; padding: 0.8rem 1rem; margin: 0.6rem 0; font-size: 0.85rem; color: #5d4a1a; }
  .copy-summary-bar { display: flex; align-items: center; gap: 0.8rem; margin: 1.5rem 0; padding: 0.7rem 1rem; background: #eef3f7; border: 1px solid #cfd8e3; border-radius: 6px; }
  .copy-summary-bar button { font: inherit; font-weight: bold; padding: 0.4rem 0.9rem; border: 1px solid #546e7a; border-radius: 6px; background: #fff; color: #37474f; cursor: pointer; }
  .copy-summary-bar button:hover { background: #546e7a; color: #fff; }
  .copy-summary-bar .copy-caption { font-size: 0.82rem; color: #607d8b; }
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
        "<table class='dense'><thead><tr>"
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
        "<table class='dense'><thead><tr>"
        "<th>티커</th><th>매수일</th><th>매수가</th><th>수량</th><th>설정일</th><th>현재가</th><th>미실현손익</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    return f"<h2>모의 투자 현황</h2><div class='chart-frame'>{table}</div>"


def _build_prediction_simulation_html(prediction_simulation: dict | None, commentary: str = "") -> str:
    """prediction_simulation: prediction_model/generate_predictions.py's output
    ({"generated_at": ..., "predictions": {ticker: {as_of_date, trend_score, val_mae,
    baseline_mae, improvement_pct, historical_avg_score}}}), loaded read-only from Drive by
    the caller (recommendation_engine) -- this experimental ML model is trained/refreshed
    manually, entirely outside collect.yml/recommend.yml (see prediction_model_spec.md
    section 7).

    `commentary` (optional, openrouter_briefing.generate_prediction_commentary's output --
    computed by the caller, same pattern as `overview`/generate_portfolio_overview) is a
    one-paragraph LLM read of the scores below, rendered right under the disclaimer.
    Commentary-only, same advisory-only constraint as the rest of the LLM sections --
    PREDICTION_COMMENTARY_SYSTEM_PROMPT explicitly forbids it from predicting future
    price/direction or touching any mechanical action.

    `trend_score` is log((매수일+1)/(매도일+1)) over the predicted next 30 days — positive
    means fresh breakouts (매수) outnumber trailing-stop breaches (매도), negative the
    opposite. It's compared against `historical_avg_score` (that ticker's own long-run
    average) rather than against zero, because 매도 structurally outnumbers 매수 for nearly
    every one of these 12 tickers (매수 = a one-day breakout event; 매도 = a state that can
    persist for many days during a drawdown) — a negative score is the norm, not a red flag
    on its own (see prediction_model_spec.md section 6.1 and the disclaimer text below,
    which explains this directly in the report itself per user request).

    Each ticker carries its own `as_of_date` rather than one report-wide date -- BTC-USD
    trades on weekends and nothing else here does, so "the most recent date" can genuinely
    differ per ticker (see generate_predictions.py's _latest_window).

    Explicitly experimental and unvalidated beyond a single train/val split -- rendered
    with a disclaimer and each ticker's own validation MAE improvement over a naive
    "predict the historical average" baseline as a rough reliability indicator, so a
    reader isn't left guessing how much to trust it. Never reorders or replaces the
    mechanical 매수/HOLD/매도 signals elsewhere in the report -- same "advisory-only"
    principle as the LLM sections. Omitted entirely if not given/empty.
    """
    predictions = (prediction_simulation or {}).get("predictions") or {}
    if not predictions:
        return ""

    # Same ticker order + category grouping as _build_summary_table_html, so the two
    # tables read as directly comparable rather than one being alphabetical (the order
    # generate_predictions.py happens to iterate its wide-format ticker array in) and the
    # other grouped by ASSET_CLASS_TICKERS' definition order.
    rows = []
    last_category = None
    for ticker, meta in data_fetcher.ASSET_CLASS_TICKERS.items():
        if ticker not in predictions:
            continue
        pred = predictions[ticker]
        category = meta.get("category", "")
        if category != last_category:
            rows.append(f"<tr class='category-row'><td colspan='6'>{_esc(category)}</td></tr>")
            last_category = category
        score_class = "pnl-positive" if pred["trend_score"] >= pred["historical_avg_score"] else "pnl-negative"
        rows.append(
            "<tr>"
            f"<td>{_esc(ticker)}</td>"
            f"<td>{_esc(meta.get('label', ''))}</td>"
            f"<td>{_esc(pred.get('as_of_date', ''))}</td>"
            f"<td class='{score_class}'>{pred['trend_score']:+.3f}</td>"
            f"<td>{pred['historical_avg_score']:+.3f}</td>"
            f"<td>{pred['improvement_pct']:.1f}%</td>"
            "</tr>"
        )
    table = (
        "<table class='dense'><thead><tr>"
        "<th>티커</th><th>자산</th><th>기준일</th><th>추세 점수(예측)</th><th>과거 평균 점수</th>"
        "<th>신뢰도(단순평균 대비 개선율)</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    disclaimer = (
        "<div class='prediction-disclaimer'>이 표는 과거 시그널·가격 패턴으로 학습한 실험적 "
        "머신러닝 모델이 향후 30일간의 <b>추세 점수</b>를 추정한 것입니다 — 위의 매수/HOLD/매도 "
        "판정(기계적 규칙 기반)과는 완전히 별개이며, 어떤 경우에도 그 판정을 대체하거나 바꾸지 "
        "않습니다.<br><br>"
        "<b>추세 점수 = log((매수일수+1) / (매도일수+1))</b> — 양수면 신고점 갱신(매수)이 "
        "트레일링 스탑 하회(매도)보다 많다는 뜻이고, 음수면 그 반대입니다.<br>"
        "<b>왜 대부분 음수로 나오는가</b>: 매수는 그날 하루 20일/100일 최고가를 새로 갱신해야만 "
        "발동하는 뾰족한 이벤트인 반면, 매도는 트레일링 스탑(최근 고점 − 3×ATR) 아래로 한 번 "
        "내려가면 가격이 다시 회복할 때까지 여러 날 계속 유지되는 상태입니다 — 그래서 12개 자산군 "
        "거의 전부 과거 전체 기간에서 매도로 분류된 날이 매수로 분류된 날보다 훨씬 많습니다. "
        "이 점수가 음수라는 사실 자체는 이상 신호가 아니라 구조적으로 당연한 결과이며, 그 자산 "
        "<b>자신의 과거 평균 점수</b>보다 지금 예측이 더 높은지/낮은지가 실제로 의미 있는 비교입니다.<br><br>"
        "\"신뢰도\"는 검증 구간에서 단순 평균 예측 대비 오차(MAE)가 얼마나 줄었는지를 나타내며, "
        "수치가 낮다고 예측이 틀렸다는 뜻은 아니지만 참고용 이상으로 받아들이지 마세요."
        "</div>"
    )
    commentary_html = f"<p class='overview'>{_esc(commentary)}</p>" if commentary else ""
    return f"<h2>AI 예측 시뮬레이션 (실험적)</h2>{disclaimer}{commentary_html}{table}"


def _build_sp500_signals_html(sp500_signals: list[dict] | None) -> str:
    """sp500_signals: recommendation_engine.get_sp500_signal_summary's output -- mechanical-
    only 매수/매도 calls (signal_engine.get_mechanical_action) across every active S&P 500
    ticker, deliberately WITHOUT news/LLM narrative (that stays scoped to the 12
    ASSET_CLASS_TICKERS to keep Exa/OpenRouter usage bounded, per CLAUDE.md). Only 매수/매도
    tickers are included (HOLD is most days for most tickers and isn't listed individually).
    Omitted entirely if empty, same "no section for nothing to show" principle used
    throughout this file.
    """
    if not sp500_signals:
        return ""

    rows = []
    for item in sorted(sp500_signals, key=lambda x: (x["action"], x["ticker"])):
        color = ACTION_COLOR.get(item["action"], "#757575")
        rows.append(
            "<tr>"
            f"<td>{_esc(item['ticker'])}</td>"
            f"<td>{_esc(item.get('description', ''))}</td>"
            f"<td>{_esc(item.get('sector', ''))}</td>"
            f"<td style='color:{color};font-weight:bold'>{item['action']}</td>"
            f"<td>{item['close']:.2f}</td>"
            "</tr>"
        )
    table = (
        "<table class='dense'><thead><tr>"
        "<th>티커</th><th>종목명</th><th>섹터</th><th>액션</th><th>종가</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    note = (
        "<p style='color:#888;font-size:0.85rem'>기계적 규칙 기반 판정만 표시됩니다 — "
        "뉴스·LLM 분석은 위 대표 자산군 12종에만 적용됩니다.</p>"
    )
    return f"<h2>S&amp;P 500 매수/매도 시그널 ({len(sp500_signals)}종목)</h2>{note}{table}"


def _build_backtest_summary_html(backtest_summary: dict | None) -> str:
    """backtest_summary: backtest.py's `python backtest.py full-universe` output
    (Drive's _backtest_summary.json -- see backtest.build_backtest_summary), loaded
    read-only by the caller. Per-ticker trade-simulation stats (n_trades/win rate/avg
    return/Kelly fraction) for both the full analysis window and a recent N-year window
    side by side, across every ASSET_CLASS_TICKERS + active S&P 500 ticker -- lets a reader
    see at a glance whether the mechanical rule's historical edge for a given ticker still
    holds in the recent window. Experimental/backward-looking, same advisory-only framing
    as the AI prediction section -- never a substitute for the mechanical action shown
    elsewhere in the report. Omitted entirely if not given/empty. Deliberately placed at the
    very end of the page (outside the copy-to-clipboard scope, see
    _build_copy_summary_bar_html) since it's reference/appendix material, not part of
    "today's" market snapshot.
    """
    if not backtest_summary or not backtest_summary.get("rows"):
        return ""

    recent_years = backtest_summary.get("recent_years", 3)
    generated_at = _esc(str(backtest_summary.get("generated_at", ""))[:10])

    def _fmt_pct(value) -> str:
        return f"{value:.1f}%" if value is not None else "—"

    def _fmt_signed_pct(value) -> str:
        return f"{value:+.1f}%" if value is not None else "—"

    rows_html = []
    for row in backtest_summary["rows"]:
        rows_html.append(
            "<tr>"
            f"<td>{_esc(row['ticker'])}</td>"
            f"<td>{_esc(row.get('category', ''))}</td>"
            f"<td>{row.get('n_trades_all', 0)}</td>"
            f"<td>{_fmt_pct(row.get('win_rate_all_pct'))}</td>"
            f"<td>{_fmt_signed_pct(row.get('avg_return_all_pct'))}</td>"
            f"<td>{_fmt_signed_pct(row.get('kelly_all_pct'))}</td>"
            f"<td>{row.get(f'n_trades_{recent_years}y', 0)}</td>"
            f"<td>{_fmt_pct(row.get(f'win_rate_{recent_years}y_pct'))}</td>"
            f"<td>{_fmt_signed_pct(row.get(f'avg_return_{recent_years}y_pct'))}</td>"
            f"<td>{_fmt_signed_pct(row.get(f'kelly_{recent_years}y_pct'))}</td>"
            "</tr>"
        )

    table = (
        "<table class='dense'><thead><tr>"
        "<th rowspan='2'>티커</th><th rowspan='2'>구분</th>"
        f"<th colspan='4'>전체 기간</th><th colspan='4'>최근 {recent_years}년</th>"
        "</tr><tr>"
        "<th>거래수</th><th>승률</th><th>평균수익률</th><th>켈리</th>"
        "<th>거래수</th><th>승률</th><th>평균수익률</th><th>켈리</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )
    disclaimer = (
        "<div class='prediction-disclaimer'>이 표는 각 종목에 톰 바소 추세추종 규칙(20일/100일 "
        "돌파 매수, 트레일링 스탑 청산)을 과거에 그대로 적용했다면 어땠을지를 계산한 것입니다 — "
        "돌파 시점 진입, 다음 청산 신호에 매도하는 거래 단위로 승률·평균 수익률·켈리 공식 기반 "
        "리스크 비율을 냈습니다. <b>과거 성과이며 미래 성과를 보장하지 않고</b>, 위 매수/HOLD/매도 "
        "판정을 대체하지 않습니다. \"거래수\"가 적은 종목(특히 최근 기간)은 통계적 신뢰도가 낮으니 "
        "참고용으로만 활용하세요."
        "</div>"
    )
    return f"<h2>전체 종목 백테스트 요약 (기준일: {generated_at})</h2>{disclaimer}{table}"


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
        "<table class='dense'><thead><tr>"
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


def _md_cell(text) -> str:
    """Escape a value for a Markdown table cell -- pipes and newlines would otherwise
    break the table's column boundaries."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _build_report_markdown(
    date: str,
    overview: str,
    results: dict,
    signal_history: dict | None,
    prediction_simulation: dict | None,
    prediction_commentary: str,
    paper_positions: list[dict] | None,
    sp500_signals: list[dict] | None = None,
) -> str:
    """Markdown mirror of everything from the page title through the AI 예측 시뮬레이션 /
    모의 투자 sections (i.e. everything *before* the "오늘의 매수/매도 시그널" heading) --
    built directly from the same Python data the HTML sections above are built from, not by
    parsing the rendered HTML, so the two can never drift out of sync with each other and
    the HTML layout is completely untouched by this feature (user request: the report's own
    look must stay as-is). Copied to the clipboard by the button rendered right before that
    heading, for pasting into another LLM for market analysis.
    """
    lines = [f"# 톰 바소 추세추종 일일 리포트 ({date})", ""]

    if overview:
        lines += ["## 오늘의 종합 총평", "", overview, ""]

    lines += [
        "## 자산군별 판정 요약",
        "",
        "| 티커 | 자산 | 카테고리 | 액션 | 종가 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for ticker, reco in results.items():
        meta = data_fetcher.ASSET_CLASS_TICKERS.get(ticker, {})
        lines.append(
            f"| {ticker} | {_md_cell(meta.get('label', ''))} | {_md_cell(meta.get('category', ''))} "
            f"| {reco['action']} | {reco['close']:.2f} |"
        )
    lines.append("")

    if sp500_signals:
        lines += [
            f"## S&P 500 매수/매도 시그널 ({len(sp500_signals)}종목)",
            "",
            "(기계적 규칙 기반 판정만 — 뉴스·LLM 분석은 위 대표 자산군에만 적용됨)",
            "",
            "| 티커 | 종목명 | 섹터 | 액션 | 종가 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in sorted(sp500_signals, key=lambda x: (x["action"], x["ticker"])):
            lines.append(
                f"| {item['ticker']} | {_md_cell(item.get('description', ''))} "
                f"| {_md_cell(item.get('sector', ''))} | {item['action']} | {item['close']:.2f} |"
            )
        lines.append("")

    if signal_history:
        tickers = list(data_fetcher.ASSET_CLASS_TICKERS)
        lines += [
            "## 최근 시그널 이력",
            "",
            "| 날짜 | " + " | ".join(tickers) + " |",
            "| --- | " + " | ".join("---" for _ in tickers) + " |",
        ]
        for date_key in sorted(signal_history, reverse=True):
            day_actions = signal_history[date_key]
            cells = [ACTION_SHORT.get(day_actions.get(t), "-") for t in tickers]
            lines.append(f"| {date_key} | " + " | ".join(cells) + " |")
        lines.append("")

    predictions = (prediction_simulation or {}).get("predictions") or {}
    if predictions:
        lines += [
            "## AI 예측 시뮬레이션 (실험적)",
            "",
            "> 과거 시그널·가격 패턴으로 학습한 실험적 머신러닝 모델의 추세 점수 예측입니다. "
            "위 매수/HOLD/매도 판정(기계적 규칙 기반)과는 별개이며 그 판정을 대체하지 않습니다. "
            "추세 점수 = log((매수일수+1)/(매도일수+1)); 매도 신호가 매수보다 구조적으로 잦아 "
            "대부분 음수로 나오는 것이 정상이며, 0이 아니라 그 자산 자신의 과거 평균과 비교해야 "
            "의미가 있습니다.",
            "",
        ]
        if prediction_commentary:
            lines += [prediction_commentary, ""]
        lines += [
            "| 티커 | 자산 | 카테고리 | 기준일 | 추세 점수(예측) | 과거 평균 점수 | 신뢰도 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for ticker, meta in data_fetcher.ASSET_CLASS_TICKERS.items():
            if ticker not in predictions:
                continue
            pred = predictions[ticker]
            lines.append(
                f"| {ticker} | {_md_cell(meta.get('label', ''))} | {_md_cell(meta.get('category', ''))} "
                f"| {pred.get('as_of_date', '')} | {pred['trend_score']:+.3f} "
                f"| {pred['historical_avg_score']:+.3f} | {pred['improvement_pct']:.1f}% |"
            )
        lines.append("")

    if paper_positions:
        lines += [
            "## 모의 투자 현황",
            "",
            "| 티커 | 매수일 | 매수가 | 수량 | 설정일 | 현재가 | 미실현손익 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for p in paper_positions:
            recorded_date = p["created_at"][:10]
            if p["current_price"] is None:
                current_cell, pnl_cell = "N/A", "N/A"
            else:
                current_cell = f"{p['current_price']:.2f}"
                pnl_cell = f"{p['unrealized_pnl']:+.2f} ({p['unrealized_pnl_pct']:+.2f}%)"
            lines.append(
                f"| {p['ticker']} | {p['entry_date']} | {p['entry_price']:.2f} | {p['quantity']} "
                f"| {recorded_date} | {current_cell} | {pnl_cell} |"
            )
        lines.append("")

    return "\n".join(lines).strip()


def _build_copy_summary_bar_html(markdown_text: str) -> str:
    """A small button that copies `markdown_text` to the clipboard via the Clipboard API.
    The Markdown itself is embedded as a JSON string literal (json.dumps handles all
    escaping) with any literal "</script" sequence additionally neutralized -- the HTML
    parser looks for that byte sequence regardless of JS string context, and `overview`/
    `prediction_commentary` are LLM-generated free text that could in principle contain it.
    """
    markdown_json = json.dumps(markdown_text).replace("</script", "<\\/script")
    return f"""<div class="copy-summary-bar">
<button id="copy-summary-btn" onclick="copyReportSummary()">📋 위 내용 Markdown으로 복사</button>
<span class="copy-caption">제목부터 이 지점 위까지(요약 표·최근 시그널 이력·AI 예측·모의 투자)를 클립보드에 복사합니다 — 다른 LLM에 시황 분석을 맡길 때 붙여넣으세요.</span>
</div>
<script>
const REPORT_MARKDOWN = {markdown_json};
function copyReportSummary() {{
  const btn = document.getElementById('copy-summary-btn');
  const original = btn.textContent;
  navigator.clipboard.writeText(REPORT_MARKDOWN).then(function() {{
    btn.textContent = '✅ 복사됨!';
    setTimeout(function() {{ btn.textContent = original; }}, 2000);
  }}, function() {{
    btn.textContent = '❌ 복사 실패 (브라우저 권한 확인)';
    setTimeout(function() {{ btn.textContent = original; }}, 2000);
  }});
}}
</script>"""


def build_daily_report_html(
    drive_db,
    results: dict,
    paper_positions: list[dict] | None = None,
    signal_history: dict | None = None,
    prediction_simulation: dict | None = None,
    sp500_signals: list[dict] | None = None,
    backtest_summary: dict | None = None,
) -> str:
    """Build the full standalone HTML report page for one day's recommendation results.

    `sp500_signals` (recommendation_engine.get_sp500_signal_summary's output, computed
    fresh every run) is likewise optional, omitted if empty (see _build_sp500_signals_html)
    — mechanical-only 매수/매도 calls across the S&P 500, deliberately without news/LLM
    narrative (kept to the 12 ASSET_CLASS_TICKERS to bound Exa/OpenRouter usage).

    `backtest_summary` (backtest.py's `python backtest.py full-universe` output, loaded
    read-only from Drive's _backtest_summary.json by the caller) is likewise optional,
    omitted if not given/empty (see _build_backtest_summary_html) — per-ticker historical
    trade-simulation stats, computed entirely outside this cron path.

    `paper_positions` (paper_trading.compute_position_returns' output, open positions only)
    is optional so existing callers/tests are unaffected — omitted entirely from the report
    if not given or empty (see _build_paper_trading_html).

    `signal_history` ({date: {ticker: action}}, already windowed by the caller — see
    recommendation_engine._recent_signal_history) is likewise optional, omitted if empty
    (see _build_signal_history_html); it's also fed to the LLM overview (generate_portfolio_
    overview) so that narrative can note recent trend shifts, not just today's snapshot.
    report_builder.py can't import recommendation_engine itself (recommendation_engine already
    imports report_builder — a back-import would be circular), so the caller always loads and
    passes this in, same as paper_positions.

    `prediction_simulation` (prediction_model/generate_predictions.py's output, loaded
    read-only from Drive's _prediction_simulation.json by the caller) is likewise optional,
    omitted if not given/empty (see _build_prediction_simulation_html) — an experimental ML
    model trained/refreshed entirely outside this cron path (see prediction_model_spec.md).
    """
    date = next(iter(results.values()))["date"] if results else datetime.date.today().isoformat()

    overview = ""
    if not config.SKIP_LLM_AND_NEWS:
        try:
            overview = openrouter_briefing.generate_portfolio_overview(results, signal_history)
        except Exception:
            pass

    prediction_commentary = ""
    if not config.SKIP_LLM_AND_NEWS and prediction_simulation and prediction_simulation.get("predictions"):
        try:
            prediction_commentary = openrouter_briefing.generate_prediction_commentary(
                prediction_simulation["predictions"]
            )
        except Exception:
            pass

    overview_html = f"<p class='overview'>{_esc(overview)}</p>" if overview else ""
    table_html = _build_summary_table_html(results)
    sp500_signals_html = _build_sp500_signals_html(sp500_signals)
    paper_html = _build_paper_trading_html(paper_positions or [])
    history_html = _build_signal_history_html(signal_history or {})
    prediction_html = _build_prediction_simulation_html(prediction_simulation, prediction_commentary)
    backtest_summary_html = _build_backtest_summary_html(backtest_summary)

    report_markdown = _build_report_markdown(
        date, overview, results, signal_history, prediction_simulation, prediction_commentary,
        paper_positions, sp500_signals,
    )
    copy_summary_html = _build_copy_summary_bar_html(report_markdown)

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
{sp500_signals_html}
{history_html}
{prediction_html}
{paper_html}
{copy_summary_html}
<h2>오늘의 매수/매도 시그널</h2>
{signal_html}
{hold_html}
{backtest_summary_html}
</body>
</html>"""


def save_report(drive_db, date: str, report_html: str) -> None:
    """Persist the report to Drive (for the Streamlit history tab) and write a local
    docs/reports/{date}.html file for recommend.yml to commit+push to GitHub Pages.

    Test publishes (config.IS_TEST_REPORT, `date` already ends with "_test" by the time
    it reaches here) are now also written to docs/reports/ and published (v3.52, reversing
    v3.27's Drive-only restriction, per explicit user request) — the "_test" suffix carries
    through to the local filename and public URL too (e.g. docs/reports/2026-08-10_test.html),
    so a test publish still can never collide with or overwrite that day's real report; it's
    simply also reachable as its own distinct public page instead of only via Drive/the
    Streamlit download button. `list_report_dates` still excludes "_test" dates from the
    Streamlit history table's main grid (see that function) — this only changes whether the
    file reaches GitHub Pages, not whether it's listed there.
    """
    drive_db.save_text(f"{REPORT_FILENAME_PREFIX}{date}.html", report_html)

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


def list_test_report_dates(drive_db) -> list[str]:
    """The counterpart to list_report_dates — dates (still carrying the "_test" suffix, e.g.
    "2026-07-24_test") for saved test/sample publishes, newest first. These never reach
    GitHub Pages (report_builder.save_report skips docs/reports/ for them), so Drive +
    this list is the only way to browse them — see app.py's "테스트/샘플 리포트 보기" toggle."""
    filenames = drive_db.list_filenames(REPORT_FILENAME_PREFIX)
    dates = [f.removeprefix(REPORT_FILENAME_PREFIX).removesuffix(".html") for f in filenames]
    dates = [d for d in dates if d.endswith("_test")]
    return sorted(dates, reverse=True)


def load_report(drive_db, date: str) -> str | None:
    return drive_db.load_text(f"{REPORT_FILENAME_PREFIX}{date}.html")

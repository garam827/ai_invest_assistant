"""Weekly HTML pages: the asset report and the special-section report.

Rendering only -- every number, stored action, and narrative string arrives precomputed
from pipelines/weekly.py; nothing here calls an LLM, Exa, or Drive. External text (LLM
output, news) is HTML-escaped. Charts are Plotly HTML, loaded from the CDN once per page.
"""
from __future__ import annotations

import pandas as pd

from invest_assistant import universe as instrument_universe
from invest_assistant.analysis import signals as signal_engine
from invest_assistant.reporting import charts as chart_builder
from invest_assistant.reporting.report import (
    ACTION_COLOR,
    ACTION_SHORT,
    BASEL3_SPECIAL_TITLE,
    CHART_PERIOD_DAYS,
    CRYPTO_SPECIAL_TITLE,
    STYLE,
    _build_news_cards_html,
    _esc,
)

CATEGORIES = ("주식", "암호화폐", "귀금속", "채권", "원자재", "통화")
REGIME_COLOR = {"위험선호": "#2e7d32", "위험회피": "#c62828", "혼조": "#757575"}
CELL_BACKGROUND = {"매수": "#c8e6c9", "HOLD": "#f5f5f5", "매도": "#ffcdd2"}
SPECIAL_TITLES = {"crypto": CRYPTO_SPECIAL_TITLE, "basel3": BASEL3_SPECIAL_TITLE}

DISCLAIMER = (
    "본 리포트는 규칙 기반 추세추종 시스템의 기록과 공개 뉴스를 정리한 참고 자료이며 투자 권유가 아닙니다. "
    "매수/HOLD/매도 표기는 일별로 저장된 기계적 판정 기록 그대로이고, LLM 해설·국면 판단·뉴스 정리는 "
    "판정이나 제안 수량을 바꾸지 않습니다. 과거 성과는 미래 수익을 보장하지 않으며 투자 판단과 책임은 "
    "투자자 본인에게 있습니다."
)

WEEKLY_STYLE = STYLE + """
  .regime { display: inline-block; padding: 2px 12px; border-radius: 999px; color: #fff; font-weight: bold; margin-right: 0.5rem; }
  .source-note { font-size: 0.78rem; color: #888; margin: 0.2rem 0 0.8rem; }
  table.dense td.num { text-align: right; font-variant-numeric: tabular-nums; }
  table.dense th.changed { background: #fff3e0; color: #e65100; }
  table.dense td.changed-cell { outline: 2px solid #ff9800; outline-offset: -2px; }
  .pos { color: #2e7d32; }
  .neg { color: #c62828; }
  .category-block { margin: 1.5rem 0; }
  .category-block h3 { margin-bottom: 0.3rem; }
  .link-list a { margin-right: 0.8rem; }
  .disclaimer { font-size: 0.78rem; color: #777; border-top: 1px solid #eee; margin-top: 3rem; padding-top: 1rem; }
  .theme-block { border: 1px solid #ddd; border-radius: 6px; padding: 0.8rem 1.2rem; margin: 1rem 0; }
  .flow-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.8rem; }
  .flow-grid .analysis { margin: 0; }
"""


def _pct_cell(value: float | None) -> str:
    if value is None:
        return "<td class='num'>-</td>"
    css = "pos" if value >= 0 else "neg"
    return f"<td class='num {css}'>{value:+.2f}%</td>"


def _action_html(action: str | None) -> str:
    if not action:
        return "<span style='color:#999'>-</span>"
    return f"<span style='color:{ACTION_COLOR.get(action, '#757575')};font-weight:bold'>{_esc(action)}</span>"


def _source_note(source: str) -> str:
    text = "LLM 총평 (참고용, 판정 불변)" if source == "llm" else "[규칙 기반 자동 생성 — LLM 미사용 또는 실패로 대체]"
    return f"<div class='source-note'>{text}</div>"


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{WEEKLY_STYLE}</style>
</head>
<body>
{body}
<p class="disclaimer">{DISCLAIMER}</p>
</body>
</html>"""


def _performance_table_html(stats: dict, grid: dict, changes: dict) -> str:
    days = sorted(grid)
    rows, last_category = [], None
    for ticker, s in stats.items():
        meta = instrument_universe.ASSET_CLASS_TICKERS.get(ticker, {})
        category = meta.get("category", "")
        if category != last_category:
            rows.append(f"<tr class='category-row'><td colspan='9'>{_esc(category)}</td></tr>")
            last_category = category
        start, end = grid[days[0]].get(ticker), grid[days[-1]].get(ticker)
        flag = " ⚑" if ticker in changes else ""
        rows.append(
            "<tr>"
            f"<td>{_esc(ticker)}{flag}</td><td>{_esc(meta.get('label', ''))}</td>"
            f"{_pct_cell(s['return_pct'])}"
            f"<td class='num'>{s['high']:.2f}</td><td class='num'>{s['low']:.2f}</td><td class='num'>{s['close']:.2f}</td>"
            f"<td>{_action_html(start)} → {_action_html(end)}</td>"
            f"{_pct_cell(s['stop_distance_pct'])}{_pct_cell(s['dc20_distance_pct'])}"
            "</tr>"
        )
    return (
        "<table class='dense'><thead><tr><th>티커</th><th>자산</th><th>주간 수익률</th><th>주간 고가</th>"
        "<th>주간 저가</th><th>주말 종가</th><th>주초→주말 시그널</th><th>트레일링 스탑까지</th>"
        "<th>DC20 상단까지</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        "<div class='source-note'>주간 수익률은 직전 주 마지막 거래일 종가 대비, 고가·저가는 이번 주 미국 거래일 봉 기준. "
        "트레일링 스탑까지 = (종가−스탑)/종가, DC20 상단까지 = (상단−종가)/종가. ⚑ = 이번 주 시그널 전환 발생.</div>"
    )


def _grid_cell(action: str | None, changed: bool) -> str:
    css = " class='changed-cell'" if changed else ""
    return (
        f"<td{css} style='background:{CELL_BACKGROUND.get(action, '#fff')};color:{ACTION_COLOR.get(action, '#999')};"
        f"font-weight:bold'>{ACTION_SHORT.get(action, '-')}</td>"
    )


def _signal_grid_html(grid: dict, changes: dict, prev_day: str, prev_actions: dict) -> str:
    tickers = list(instrument_universe.ASSET_CLASS_TICKERS)
    header = "".join(
        f"<th class='changed'>{_esc(t)}</th>" if t in changes else f"<th>{_esc(t)}</th>" for t in tickers
    )
    changed_cells = {(day, t) for t, items in changes.items() for day, _, _ in items}
    rows = [
        f"<tr style='opacity:0.6'><td>{_esc(prev_day)} (직전 주)</td>"
        + "".join(_grid_cell(prev_actions.get(t), False) for t in tickers) + "</tr>"
    ]
    for day in sorted(grid):
        cells = "".join(_grid_cell(grid[day].get(t), (day, t) in changed_cells) for t in tickers)
        rows.append(f"<tr><td>{_esc(day)}</td>{cells}</tr>")
    return (
        "<table class='dense'><thead><tr><th>거래일</th>" + header + "</tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
        "<div class='source-note'>B=매수 · H=HOLD · S=매도 · -=기록 없음. 저장된 일별 판정 기록 그대로입니다"
        "(매도는 종가가 트레일링 스탑 아래인 동안 매일 기록됨). 주황 머리글·테두리는 전날 기록과 달라진 시그널 전환입니다.</div>"
    )


def _ticker_chart_html(raw_df: pd.DataFrame, ticker: str, last_day: str) -> str:
    df = raw_df[pd.to_datetime(raw_df["Date"]) <= pd.Timestamp(last_day)]
    view = chart_builder.slice_to_period(signal_engine.compute_signals(df), CHART_PERIOD_DAYS)
    fig = chart_builder.build_ticker_chart_figure(ticker, view)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _category_sections_html(briefing: dict, stats: dict, frames: dict, last_day: str) -> str:
    blocks = []
    for category in CATEGORIES:
        tickers = [t for t in stats if instrument_universe.ASSET_CLASS_TICKERS.get(t, {}).get("category") == category]
        if not tickers:
            continue
        charts = []
        for ticker in tickers:
            if ticker not in frames:
                continue
            try:
                chart = _ticker_chart_html(frames[ticker], ticker, last_day)
            except Exception:
                continue
            label = instrument_universe.ASSET_CLASS_TICKERS[ticker]["label"]
            charts.append(f"<h4>{_esc(ticker)} — {_esc(label)}</h4><div class='chart-frame'>{chart}</div>")
        chart_block = (
            f"<details><summary>📈 {_esc(category)} 일봉 차트 ({CHART_PERIOD_DAYS // 30}개월, {len(charts)}개)</summary>"
            + "".join(charts) + "</details>"
            if charts else ""
        )
        blocks.append(
            f"<div class='category-block'><h3>{_esc(category)}</h3>"
            f"<div class='analysis'>{_esc(briefing.get(category, ''))}</div>{chart_block}</div>"
        )
    return "".join(blocks)


def _macro_table_html(macro: dict) -> str:
    if not macro:
        return "<p>매크로 지표를 조회하지 못해 이 섹션을 생략합니다.</p>"
    rows = []
    for item in macro.values():
        yield_pct = item.get("format") == "yield_pct"
        start, end = item["start_value"], item["end_value"]
        delta = end - start
        if yield_pct:
            values = f"<td class='num'>{start:.3f}%</td><td class='num'>{end:.3f}%</td><td class='num'>{delta:+.3f}%p</td>"
        else:
            values = f"<td class='num'>{start:.2f}</td><td class='num'>{end:.2f}</td><td class='num'>{delta:+.2f}</td>"
        rows.append(
            f"<tr><td>{_esc(item['label'])}</td><td>{_esc(item['start_date'])}</td><td>{_esc(item['end_date'])}</td>{values}</tr>"
        )
    return (
        "<table class='dense'><thead><tr><th>지표</th><th>주초 기준일</th><th>주말 기준일</th><th>주초(직전 주 종가)</th>"
        "<th>주말</th><th>변화폭</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def build_weekly_asset_html(
    window,
    stats: dict,
    grid: dict,
    changes: dict,
    prev_actions: dict,
    briefing: dict,
    briefing_source: str,
    macro: dict,
    checkpoints: str,
    checkpoints_source: str,
    frames: dict,
    daily_links: list[tuple[str, str]],
    special_href: str | None,
) -> str:
    title = f"톰 바소 추세추종 주간 자산 리포트 {window.week} ({window.period})"
    regime = briefing.get("국면", "혼조")
    bar_fig = chart_builder.build_weekly_return_bar_figure({t: s["return_pct"] for t, s in stats.items()})
    bar_html = bar_fig.to_html(full_html=False, include_plotlyjs="cdn")

    special_link = (
        f"<a href='{_esc(special_href)}'>🪙🏦 특별 섹션 주간 리포트 (크립토 · 바젤3)</a>"
        if special_href else "<span>특별 섹션 주간 리포트는 이번 주 생성되지 않았습니다.</span>"
    )
    daily_html = " ".join(f"<a href='{_esc(href)}'>{_esc(day)}</a>" for day, href in daily_links) or "링크할 일일 리포트가 없습니다."

    body = f"""<div class="page-header">
<h1>{_esc(title)}</h1>
<div class="chart-legend-key">미국 거래일 {_esc(window.trading_days[0])} ~ {_esc(window.last_day)} 종가 기준<br>BB=볼린저밴드 · DC20/DC100=Donchian채널<br>손절선=트레일링 스탑(고점−3×ATR)</div>
</div>
<h2>이번 주 한 줄 요약</h2>
<div class="overview"><span class="regime" style="background:{REGIME_COLOR.get(regime, '#757575')}">{_esc(regime)}</span>{_esc(briefing.get('요약', ''))}<br><br>{_esc(briefing.get('근거', ''))}</div>
{_source_note(briefing_source)}
<h2>주간 성과표</h2>
{_performance_table_html(stats, grid, changes)}
<h2>주간 수익률 순위</h2>
<div class="chart-frame">{bar_html}</div>
<h2>시그널 변화 지도</h2>
{_signal_grid_html(grid, changes, window.prev_close_date, prev_actions)}
<h2>자산군별 분석</h2>
{_category_sections_html(briefing, stats, frames, window.last_day)}
<h2>매크로 지표 주간 변화</h2>
{_macro_table_html(macro)}
<h2>다음 주 체크포인트</h2>
<div class="analysis">{_esc(checkpoints)}</div>
{_source_note(checkpoints_source)}
<h2>관련 페이지</h2>
<p class="link-list">{special_link}</p>
<p class="link-list">이번 주 일일 리포트: {daily_html}</p>"""
    return _page(title, body)


def _numbers_table_html(theme: dict) -> str:
    if not theme["numbers"]:
        note = "기사에서 확인된 수치가 없습니다." if theme["source"] == "llm" else "LLM 정리가 없어 수치 추적표를 생략합니다(수치를 임의로 만들지 않음)."
        return f"<p class='source-note'>{note}</p>"
    rows = "".join(
        f"<tr><td>{_esc(r['metric'])}</td><td class='num'>{_esc(r['value'])}</td><td>{_esc(r['as_of'])}</td>"
        f"<td style='text-align:left'>{_esc(r['source'])}</td></tr>"
        for r in theme["numbers"]
    )
    dropped = (
        f"<div class='source-note'>원문 기사에서 확인되지 않은 수치 {theme['numbers_dropped']}건은 제외했습니다.</div>"
        if theme["numbers_dropped"] else ""
    )
    return (
        "<table class='dense'><thead><tr><th>지표</th><th>값</th><th>기준일</th><th>근거 기사</th></tr></thead><tbody>"
        + rows + "</tbody></table>" + dropped
    )


def _theme_signals_html(theme: dict, stats: dict, grid: dict) -> str:
    rows = []
    days = sorted(grid)
    for ticker in theme["assets"]:
        if ticker not in stats:
            continue
        cells = "".join(f"<td>{_action_html(grid[d].get(ticker))}</td>" for d in days)
        rows.append(f"<tr><td>{_esc(ticker)}</td>{_pct_cell(stats[ticker]['return_pct'])}{cells}</tr>")
    header = "".join(f"<th>{_esc(d[5:])}</th>" for d in days)
    return (
        f"<table class='dense'><thead><tr><th>자산</th><th>주간 수익률</th>{header}</tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def build_weekly_special_html(window, special: dict, stats: dict, grid: dict, asset_href: str) -> str:
    title = f"특별 섹션 주간 리포트 {window.week} ({window.period})"
    themes = special["themes"]
    flows, numbers, connections, news = [], [], [], []
    for name, theme in themes.items():
        heading = SPECIAL_TITLES.get(name, theme["label"])
        coverage = (
            f"일별 기록 {len(theme['record_days'])}일(브리핑 텍스트 {len(theme['texts_days'])}일) · "
            f"주간 추가 검색 {len(theme['fresh'])}건"
        )
        flows.append(
            f"<div class='theme-block'><h3>{_esc(heading)}</h3><div class='source-note'>{coverage}</div>"
            "<div class='flow-grid'>"
            + "".join(
                f"<div><h4>{label}</h4><div class='analysis'>{_esc(theme['flows'].get(key, '없음'))}</div></div>"
                for key, label in (("반복", "주중 반복 등장"), ("신규", "새로 등장"), ("소멸", "사라진 이슈"))
            )
            + f"</div>{_source_note(theme['source'])}</div>"
        )
        numbers.append(f"<h3>{_esc(theme['label'])}</h3>{_numbers_table_html(theme)}")
        connections.append(
            f"<div class='theme-block'><h3>{_esc(theme['label'])} ↔ {_esc(' · '.join(theme['assets']))}</h3>"
            f"{_theme_signals_html(theme, stats, grid)}<div class='analysis'>{_esc(theme['connection'])}</div></div>"
        )
        if theme["news"]:
            news.append(
                f"<details><summary>📰 {_esc(theme['label'])} 참고 뉴스</summary>{_build_news_cards_html(theme['news'])}</details>"
            )

    body = f"""<div class="page-header">
<h1>{_esc(title)}</h1>
<div class="chart-legend-key"><a href="{_esc(asset_href)}">← 주간 자산 리포트</a></div>
</div>
<h2>이번 주 핵심 5가지</h2>
<div class="analysis">{_esc(special['highlights'])}</div>
{_source_note(special['source'])}
<h2>테마별 흐름</h2>
{''.join(flows)}
<h2>수치 추적표</h2>
<p class="source-note">기사에 명시된 수치만 싣고, 원문에서 다시 확인되지 않는 값은 제외합니다.</p>
{''.join(numbers)}
<h2>자산과의 연결</h2>
<p class="source-note">시그널은 저장된 일별 기계적 판정 기록이며, 아래 해석은 참고용으로 판정에 영향을 주지 않습니다.</p>
{''.join(connections)}
<h2>다음 주에 볼 것</h2>
<div class="analysis">{_esc(special['next_week'])}</div>
<h2>참고 뉴스</h2>
{''.join(news) or '<p>참고 뉴스가 없습니다.</p>'}"""
    return _page(title, body)

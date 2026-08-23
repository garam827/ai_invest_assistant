"""Price-free chart tooling for public/monetized blog content.

Unlike chart_builder.py's candlestick charts (used by the Streamlit UI and the free,
non-monetized GitHub Pages report), nothing here displays absolute price levels computed
from our own yfinance-sourced data -- only our own derived signal classification (매수/HOLD/
매도), relative (%) returns, or a link out to a chart Yahoo Finance itself hosts and serves
under their own terms. A candlestick chart built from our own data is still substantially a
graphical reproduction of Yahoo-sourced price data regardless of styling, which yfinance/
Yahoo's own terms restrict to personal/non-commercial use -- content meant for a monetized
blog needs to abstract price out of anything *we* render, or link out to a source that's
already licensed to display it (user decision, 2026-08-19 session).

Three things this module provides:
- build_state_timeline_figure: horizontal timeline of 매수/HOLD/매도 state over a recent
  window -- purely our own classification, no price axis. Takes an already-computed
  signal_engine.compute_signals() DataFrame over the *full* history, same convention as
  chart_builder.build_ticker_chart_figure (compute once, window per-function so Donchian-100/
  ATR's lookback isn't distorted by an earlier display-window slice).
- build_return_since_entry_figure: % return curve from the day the CURRENT signal state
  began to today -- a relative/normalized transformation, never an absolute price axis. Same
  full-history-DataFrame convention as above.
- build_yahoo_finance_chart_url: generates a deep link to Yahoo Finance's own interactive
  chart page, pre-configured with (almost exactly) this project's own indicator set --
  Donchian(20)/Donchian(100)/ATR Trailing Stop(14,3)/Ichimoku(9,26,52,26) all match
  signal_engine.py's own defaults, likely because those are just the conventional default
  periods for each indicator rather than a deliberate match. We display zero price data
  ourselves here; Yahoo renders its own chart on its own page.
"""
from __future__ import annotations

import base64
import datetime

import pandas as pd
import plotly.graph_objects as go

import signal_engine
from chart_builder import FONT_FAMILY

ACTION_COLOR = {"매수": "#2e7d32", "HOLD": "#9e9e9e", "매도": "#c62828"}
ACTION_FILL = {"매수": "rgba(46,125,50,0.15)", "HOLD": "rgba(158,158,158,0.15)", "매도": "rgba(198,40,40,0.15)"}

# Reverse-engineered from a real "Share" link generated on finance.yahoo.com/chart/SPY (user
# provided, 2026-08-19) -- Yahoo encodes the chart's full layout/indicator state as this JSON
# blob, base64'd into the URL's hash fragment. Kept as a raw string template (not rebuilt as
# a Python dict + json.dumps) so byte-for-byte quirks survive untouched -- notably, several
# "studies" dict keys embed U+200C (zero-width non-joiner) characters around the indicator
# name, which is presumably how Yahoo's frontend keeps otherwise-identical-looking keys
# distinct; round-tripping through json.loads/dumps would risk silently normalizing those
# away. "SPY" appears exactly 3 times in this template (the chart panel's display label plus
# the symbol in two places) and is replaced everywhere via a single .replace() call, since no
# other field happens to equal that literal string. Verified: standard base64 alphabet (the
# real captured URL contains "+" and no "-"/"_", ruling out the URL-safe variant) with
# padding stripped (the captured URL had no trailing "="), matching what
# base64.b64encode(...).rstrip("=") produces.
#
# Caveat this hasn't been used to verify: SPY's "symbolObject" metadata says
# "market":"us_market","quoteType":"ETF" -- true for every ASSET_CLASS_TICKERS ETF (TLT, GLD,
# QQQ, DBC, USO, UNG, DBA, DBB, UUP), but almost certainly wrong for BTC-USD (a
# cryptocurrency, not an ETF). Whether Yahoo's frontend self-corrects this from the URL path
# regardless of what the hash fragment claims, or a mismatched quoteType breaks the crypto
# chart specifically, hasn't been checked in an actual browser -- verify a generated BTC-USD
# link before publishing anything built on it.
_YAHOO_CHART_TEMPLATE = (
    '{"layout":{"interval":"day","periodicity":1,"timeUnit":null,"candleWidth":5.488095238095238,'
    '"flipped":false,"volumeUnderlay":true,"adj":true,"crosshair":true,"chartType":"candle",'
    '"extended":false,"marketSessions":{},"aggregationType":"ohlc","chartScale":"linear","studies":{'
    '"‌vol undr‌":{"type":"vol undr","inputs":{"Series":"series","id":"‌vol undr‌",'
    '"display":"‌vol undr‌"},"outputs":{"Up Volume":"#0dbd6eee","Down Volume":"#ff5547ee"},'
    '"panel":"‌vol undr‌","parameters":{"chartName":"chart","editMode":true,'
    '"panelName":"‌vol undr‌","yaxisDisplayValue":"right","flippedEnabled":false},'
    '"disabled":false},"‌Bollinger Bands‌ (14,2,ema,y)":{"type":"Bollinger Bands","inputs":'
    '{"Period":"14","Field":"field","Standard Deviations":2,"Moving Average Type":"exponential",'
    '"Channel Fill":true,"id":"‌Bollinger Bands‌ (14,2,ema,y)",'
    '"display":"‌Bollinger Bands‌ (14,2,ema,y)"},"outputs":{"Bollinger Bands Top":'
    '{"width":1,"pattern":"solid","color":"auto"},"Bollinger Bands Median":{"width":1,'
    '"pattern":"solid","color":"#ffffff75"},"Bollinger Bands Bottom":{"width":1,"pattern":"solid",'
    '"color":"auto"}},"panel":"chart","parameters":{"chartName":"chart","editMode":true,'
    '"panelName":"chart","underlayEnabled":true},"disabled":false},'
    '"‌ATR Trailing Stop‌ (14,3,squarewave,n)":{"type":"ATR Trailing Stop","inputs":'
    '{"Period":"14","Multiplier":3,"Plot Type":"squarewave","HighLow":false,'
    '"id":"‌ATR Trailing Stop‌ (14,3,squarewave,n)",'
    '"display":"‌ATR Trailing Stop‌ (14,3,squarewave,n)"},"outputs":{"Buy Stops":'
    '{"width":1,"pattern":"solid","color":"#00000000"},"Sell Stops":{"width":5,"pattern":"solid",'
    '"color":"#ea1d2cff"}},"panel":"chart","parameters":{"chartName":"chart","editMode":true,'
    '"panelName":"","underlayEnabled":false},"disabled":false},'
    '"‌Donchian Channel‌ (20,20,n)":{"type":"Donchian Channel","inputs":{"High Period":20,'
    '"Low Period":20,"Channel Fill":false,"id":"‌Donchian Channel‌ (20,20,n)",'
    '"display":"‌Donchian Channel‌ (20,20,n)"},"outputs":{"Donchian High":{"width":1,'
    '"pattern":"solid","color":"#00afedff"},"Donchian Median":{"color":"#00000000"},'
    '"Donchian Low":{"width":1,"pattern":"solid","color":"#00afedff"}},"panel":"chart",'
    '"parameters":{"chartName":"chart","editMode":true,"panelName":"chart"},"disabled":false},'
    '"‌Ichimoku Clouds‌ (9,26,52,26)":{"type":"Ichimoku Clouds","inputs":'
    '{"Conversion Line Period":9,"Base Line Period":26,"Leading Span B Period":52,'
    '"Lagging Span Period":26,"id":"‌Ichimoku Clouds‌ (9,26,52,26)",'
    '"display":"‌Ichimoku Clouds‌ (9,26,52,26)"},"outputs":{"Conversion Line":'
    '{"color":"#00000000"},"Base Line":{"color":"#00000000"},"Leading Span A":'
    '{"color":"#ea1d2cff"},"Leading Span B":{"color":"#00bff0ff"},"Lagging Span":'
    '{"color":"#00000000"}},"panel":"chart","parameters":{"chartName":"chart","editMode":true,'
    '"underlayEnabled":true,"panelName":"chart"},"disabled":false},'
    '"‌Donchian Channel‌ (100,100,n)":{"type":"Donchian Channel","inputs":'
    '{"High Period":"100","Low Period":"100","Channel Fill":false,'
    '"id":"‌Donchian Channel‌ (100,100,n)","display":"‌Donchian Channel‌ (100,100,n)"},'
    '"outputs":{"Donchian High":{"width":1,"pattern":"solid","color":"#00a553ff"},'
    '"Donchian Median":{"color":"#00000000"},"Donchian Low":{"width":1,"pattern":"solid",'
    '"color":"#00a553ff"}},"panel":"chart","parameters":{"chartName":"chart","editMode":true,'
    '"panelName":"chart"},"disabled":false}},"panels":{"chart":{"percent":0.8,"display":"SPY",'
    '"chartName":"chart","index":0,"yAxis":{"name":"chart","position":null},"yaxisLHS":[],'
    '"yaxisRHS":["chart"]},"‌vol undr‌":{"percent":0.2,"display":"‌vol undr‌",'
    '"chartName":"chart","index":1,"yAxis":{"name":"‌vol undr‌","position":"right"},'
    '"yaxisLHS":[],"yaxisRHS":["‌vol undr‌"]}},"setSpan":{"multiplier":1,"base":"year",'
    '"periodicity":{"period":1,"timeUnit":"day"},"showEventsQuote":true,"forceLoad":true},'
    '"outliers":false,"animation":true,"headsUp":{"static":true,"dynamic":false,"floating":false},'
    '"lineWidth":2,"fullScreen":true,"stripedBackground":false,"color":"#0081f2",'
    '"crosshairSticky":false,"dontSaveRangeToLayout":true,"symbols":[{"symbol":"SPY",'
    '"symbolObject":{"symbol":"SPY","market":"us_market","quoteType":"ETF",'
    '"exchangeTimeZone":"America/New_York","period1":1723993200,"period2":1787151600},'
    '"periodicity":1,"interval":"day","timeUnit":null,"setSpan":{"multiplier":1,"base":"year",'
    '"periodicity":{"period":1,"timeUnit":"day"},"showEventsQuote":true,"forceLoad":true}}],'
    '"renderers":[],"studyLegend":{"expanded":false}},"events":{"divs":true,"splits":true,'
    '"tradingHorizon":"none","sigDevEvents":[]},"drawings":null,"preferences":{}}'
)


def build_yahoo_finance_chart_url(
    ticker: str, lookback_years: int = 2, as_of: datetime.date | None = None
) -> str:
    """Deep link to Yahoo Finance's own interactive chart for `ticker`, pre-configured with
    this project's indicator set (see _YAHOO_CHART_TEMPLATE's comment) -- we display zero
    price data ourselves, Yahoo renders its own chart on its own page under its own terms.

    `as_of` (default today) anchors the window; `lookback_years` (default 2, matching the
    captured example) sets how far back period1 goes. Both bounds are set at 15:00 UTC to
    match the captured example's own timestamps exactly (not otherwise significant).
    """
    as_of = as_of or datetime.date.today()
    period2 = int(datetime.datetime(as_of.year, as_of.month, as_of.day, 15, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
    period1_date = as_of - datetime.timedelta(days=365 * lookback_years)
    period1 = int(
        datetime.datetime(
            period1_date.year, period1_date.month, period1_date.day, 15, 0, 0, tzinfo=datetime.timezone.utc
        ).timestamp()
    )

    payload = (
        _YAHOO_CHART_TEMPLATE.replace('"SPY"', f'"{ticker}"')
        .replace("1723993200", str(period1))
        .replace("1787151600", str(period2))
    )
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"https://finance.yahoo.com/chart/{ticker}#{encoded}"


def _daily_actions(signals: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day: Date, Close (kept only for the return-curve math in
    build_return_since_entry_figure -- never plotted directly or exposed on any axis), and
    action (매수/HOLD/매도) -- signal_engine.get_mechanical_action's exact rules, applied day
    by day instead of just to the latest row (same per-day approach as
    recommendation_engine._signal_history_for_ticker, kept separate here so this module
    doesn't depend on recommendation_engine).
    """
    actions = [
        signal_engine.get_mechanical_action(
            {
                "breakout_20": bool(row["Breakout_20"]),
                "breakout_100": bool(row["Breakout_100"]),
                "exit_signal": bool(row["Exit_Signal"]),
            }
        )
        for _, row in signals.iterrows()
    ]
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(signals["Date"]).reset_index(drop=True),
            "Close": signals["Close"].reset_index(drop=True),
            "action": actions,
        }
    )


def _collapse_into_runs(daily: pd.DataFrame) -> list[dict]:
    """Contiguous same-action stretches -- {"action", "start", "end"} -- so the timeline
    chart draws one colored band per run instead of one per day."""
    runs = []
    start_idx = 0
    for i in range(1, len(daily) + 1):
        if i == len(daily) or daily["action"].iloc[i] != daily["action"].iloc[start_idx]:
            runs.append(
                {
                    "action": daily["action"].iloc[start_idx],
                    "start": daily["Date"].iloc[start_idx],
                    "end": daily["Date"].iloc[i - 1],
                }
            )
            start_idx = i
    return runs


def build_state_timeline_figure(signals: pd.DataFrame, days: int = 60, ticker_label: str = "") -> go.Figure:
    """Horizontal timeline of 매수/HOLD/매도 state over the most recent `days` calendar
    days, drawn as colored background bands (fig.add_vrect) -- no price trace, no price
    axis. `signals` must already have signal_engine.compute_signals()'s columns, computed
    over the full history (see module docstring).
    """
    daily = _daily_actions(signals)
    cutoff = daily["Date"].max() - pd.Timedelta(days=days)
    daily = daily[daily["Date"] >= cutoff].reset_index(drop=True)
    if daily.empty:
        raise ValueError("no signal data in the requested window")

    runs = _collapse_into_runs(daily)

    fig = go.Figure()
    for run in runs:
        fig.add_vrect(
            x0=run["start"],
            x1=run["end"] + pd.Timedelta(days=1),
            fillcolor=ACTION_COLOR.get(run["action"], "#999"),
            opacity=0.55,
            line_width=0,
        )
    # add_vrect doesn't register a legend entry on its own -- one dummy invisible marker
    # per action actually present in this window stands in for it.
    for action in ACTION_COLOR:
        if action in daily["action"].values:
            fig.add_trace(
                go.Scatter(
                    x=[None], y=[None], mode="markers", marker=dict(size=10, color=ACTION_COLOR[action]), name=action
                )
            )

    title = f"{ticker_label} 최근 시그널 상태" if ticker_label else "최근 시그널 상태"
    fig.update_yaxes(visible=False, range=[-1, 1], fixedrange=True)
    fig.update_xaxes(type="date", range=[daily["Date"].min(), daily["Date"].max()])
    fig.update_layout(
        title=title,
        height=160,
        template="plotly_white",
        font=dict(family=FONT_FAMILY),
        margin=dict(l=10, r=10, t=45, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5),
    )
    return fig


def build_return_since_entry_figure(signals: pd.DataFrame, ticker_label: str = "") -> go.Figure:
    """% return curve from the day the CURRENT signal state began (the most recent 매수/매도
    trigger, or further back if today's row is a continuing HOLD) through today -- e.g. "이
    시그널이 뜬 뒤 지금까지 +N% 움직였다." Computed from Close, but Close itself never appears
    on an axis or in a hover label -- only the entry-day-normalized (0%) percent change.

    If the current streak's start predates the earliest row in `signals`, this understates
    the true streak length (treats the earliest available row as "entry") rather than
    failing -- an acceptable limitation for an illustrative chart, not a precise backtest.
    """
    daily = _daily_actions(signals)
    if daily.empty:
        raise ValueError("no signal data available")

    current_action = daily["action"].iloc[-1]
    start_idx = len(daily) - 1
    while start_idx > 0 and daily["action"].iloc[start_idx - 1] == current_action:
        start_idx -= 1

    window = daily.iloc[start_idx:].reset_index(drop=True)
    entry_close = window["Close"].iloc[0]
    returns_pct = (window["Close"] / entry_close - 1) * 100

    color = ACTION_COLOR.get(current_action, "#757575")
    fill = ACTION_FILL.get(current_action, "rgba(117,117,117,0.15)")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=window["Date"],
            y=returns_pct,
            mode="lines",
            line=dict(color=color, width=2.5),
            fill="tozeroy",
            fillcolor=fill,
            name=current_action,
            showlegend=False,
            hovertemplate="%{x|%Y-%m-%d}: %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dot", line_color="#999")

    entry_date_str = window["Date"].iloc[0].strftime("%Y-%m-%d")
    prefix = f"{ticker_label} " if ticker_label else ""
    fig.update_yaxes(title="진입 시점 대비 수익률 (%)")
    fig.update_xaxes(title="")
    fig.update_layout(
        title=f"{prefix}현재 {current_action} 시그널 이후 수익률 ({entry_date_str}~)",
        height=280,
        template="plotly_white",
        font=dict(family=FONT_FAMILY),
        margin=dict(l=50, r=20, t=45, b=30),
    )
    return fig

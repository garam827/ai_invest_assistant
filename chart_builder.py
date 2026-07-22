"""Builds the shared candlestick+indicator Plotly figure.

Streamlit-independent (unlike app.py's render_ticker_chart, which also handles metrics,
layout, and the LLM recommendation section) so the exact same chart can be embedded both
in the Streamlit UI and in report_builder.py's daily HTML report (fig.to_html(), rendered
client-side as interactive JS/SVG in whichever browser opens it — no server-side/headless
rendering involved, so there's no CJK font installation step needed anywhere in the pipeline).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config

# Explicit CJK-first font stack so Korean labels/legend render consistently across whatever
# font the viewer's OS/browser defaults to, in priority order with a generic sans-serif
# fallback last.
FONT_FAMILY = "Nanum Gothic, Malgun Gothic, Noto Sans CJK KR, Apple SD Gothic Neo, sans-serif"


def slice_to_period(signals: pd.DataFrame, days: int | None) -> pd.DataFrame:
    """Slice an already-computed signal_engine.compute_signals() DataFrame to the most
    recent `days` calendar days for display (`days=None` returns it unsliced). Callers
    compute_signals() on the *full* history first — Donchian-100/ATR need that lookback so
    the left edge of the displayed window isn't distorted — and slice only for the chart.
    """
    if days is None:
        return signals
    return signals[signals["Date"] >= signals["Date"].max() - pd.Timedelta(days=days)]


def build_ticker_chart_figure(ticker: str, view: pd.DataFrame) -> go.Figure:
    """`view` must already have signal_engine.compute_signals()'s columns, sliced to the
    desired display period — use slice_to_period() to build it correctly."""
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        row_heights=[0.6, 0.2, 0.2],  # 캔들:거래량:ATR = 3:1:1
        subplot_titles=(f"{ticker} 캔들차트 + 시그널 지표", "거래량 (거래량 급증일 강조)", "ATR (14일)"),
    )

    fig.add_trace(
        go.Candlestick(
            x=view["Date"],
            open=view["Open"],
            high=view["High"],
            low=view["Low"],
            close=view["Close"],
            name="가격",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["BB_Upper"], name="BB상단", line=dict(color="rgba(120,144,156,0.6)", width=1)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["BB_Lower"],
            name="BB하단",
            line=dict(color="rgba(120,144,156,0.6)", width=1),
            fill="tonexty",
            fillcolor="rgba(120,144,156,0.12)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["BB_Middle"], name="BB중심", line=dict(color="#546e7a", width=1, dash="dash")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Upper_20"], name="DC20상단", line=dict(color="#42a5f5", width=1, dash="dot")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Lower_20"], name="DC20하단", line=dict(color="#42a5f5", width=1, dash="dot")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Upper_100"], name="DC100상단", line=dict(color="#7e57c2", width=1, dash="dash")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Lower_100"], name="DC100하단", line=dict(color="#7e57c2", width=1, dash="dash")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Trailing_Stop"], name="손절선", line=dict(color="#ef5350", width=1.5)),
        row=1,
        col=1,
    )

    # Ichimoku Kinko Hyo (일목균형표) — chart-only reference overlay, see signal_engine.calculate_ichimoku.
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Ichimoku_Tenkan"], name="전환선", line=dict(color="#e67e22", width=1)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Ichimoku_Kijun"], name="기준선", line=dict(color="#2980b9", width=1)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["Ichimoku_Chikou"],
            name="후행스팬",
            line=dict(color="#8e44ad", width=1, dash="dot"),
        ),
        row=1,
        col=1,
    )

    # Cloud (Senkou A/B) drawn the traditional way — extended `displacement` business days past
    # the last candle. Senkou_A/B columns are already displaced (shift(+displacement)) so they
    # cover the historical portion; the tail of the "_Raw" (undisplaced) columns supplies the
    # future-projecting tip, continuing the same series with no gap (see calculate_ichimoku).
    displacement = config.ICHIMOKU_DISPLACEMENT
    if len(view) > displacement:
        future_dates = pd.bdate_range(start=view["Date"].max() + pd.Timedelta(days=1), periods=displacement)
        cloud_dates = pd.concat([view["Date"], pd.Series(future_dates)], ignore_index=True)
        cloud_a = pd.concat(
            [view["Ichimoku_SenkouA"], view["Ichimoku_SenkouA_Raw"].iloc[-displacement:].reset_index(drop=True)],
            ignore_index=True,
        )
        cloud_b = pd.concat(
            [view["Ichimoku_SenkouB"], view["Ichimoku_SenkouB_Raw"].iloc[-displacement:].reset_index(drop=True)],
            ignore_index=True,
        )
    else:
        cloud_dates, cloud_a, cloud_b = view["Date"], view["Ichimoku_SenkouA"], view["Ichimoku_SenkouB"]

    fig.add_trace(
        go.Scatter(x=cloud_dates, y=cloud_a, name="선행스팬A", line=dict(color="rgba(46,204,113,0.6)", width=1)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=cloud_dates,
            y=cloud_b,
            name="선행스팬B",
            line=dict(color="rgba(231,76,60,0.6)", width=1),
            fill="tonexty",
            fillcolor="rgba(149,165,166,0.18)",
        ),
        row=1,
        col=1,
    )

    buy_points = view[view["Buy_Trigger"]]
    fig.add_trace(
        go.Scatter(
            x=buy_points["Date"],
            y=buy_points["Low"] * 0.99,
            mode="markers",
            name="매수",
            marker=dict(symbol="triangle-up", size=11, color="#2e7d32", line=dict(width=1, color="#1b5e20")),
        ),
        row=1,
        col=1,
    )
    sell_points = view[view["Sell_Trigger"]]
    fig.add_trace(
        go.Scatter(
            x=sell_points["Date"],
            y=sell_points["High"] * 1.01,
            mode="markers",
            name="매도",
            marker=dict(symbol="triangle-down", size=11, color="#c62828", line=dict(width=1, color="#7f0000")),
        ),
        row=1,
        col=1,
    )

    volume_colors = ["#ff7043" if surge else "#90a4ae" for surge in view["Volume_Surge"]]
    fig.add_trace(go.Bar(x=view["Date"], y=view["Volume"], name="거래량", marker_color=volume_colors), row=2, col=1)

    fig.add_trace(go.Scatter(x=view["Date"], y=view["ATR"], name="ATR", line=dict(color="#ffa726", width=1.5)), row=3, col=1)

    fig.update_layout(
        height=950,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        template="plotly_white",
        font=dict(family=FONT_FAMILY),
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=60, b=20, r=120, l=40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(150,150,150,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(150,150,150,0.15)")

    return fig

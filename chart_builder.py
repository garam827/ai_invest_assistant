"""Builds the shared candlestick+indicator Plotly figure.

Streamlit-independent (unlike app.py's render_ticker_chart, which also handles metrics,
layout, and the LLM recommendation section) so the exact same chart can be rendered both
in the Streamlit UI (browser renders the Korean text with the viewer's own fonts, so this
doesn't matter there) and as a static PNG for Telegram (via kaleido, see telegram_notifier.py
— kaleido renders headlessly with Chromium, and a bare Ubuntu CI runner has no CJK font
installed by default, so Korean text silently drops to tofu/blank glyphs unless (a) a CJK
font is installed on the runner — see .github/workflows/recommend.yml — and (b) the figure
explicitly requests a font family that includes one, which is what FONT_FAMILY below is for).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Requested in priority order; Chromium/kaleido and browsers both fall back to the next
# family (or their own default) if an earlier one isn't installed, so listing Windows/macOS
# names here doesn't break other environments — it's just a wishlist.
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
        row_heights=[0.6, 0.2, 0.2],
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
        go.Scatter(x=view["Date"], y=view["BB_Upper"], name="볼린저 상단", line=dict(color="rgba(120,144,156,0.6)", width=1)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["BB_Lower"],
            name="볼린저 하단",
            line=dict(color="rgba(120,144,156,0.6)", width=1),
            fill="tonexty",
            fillcolor="rgba(120,144,156,0.12)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["BB_Middle"], name="볼린저 중심선(20일 SMA)", line=dict(color="#546e7a", width=1, dash="dash")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Upper_20"], name="Donchian 상단(20일)", line=dict(color="#42a5f5", width=1, dash="dot")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Lower_20"], name="Donchian 하단(20일)", line=dict(color="#42a5f5", width=1, dash="dot")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Upper_100"], name="Donchian 상단(100일)", line=dict(color="#7e57c2", width=1, dash="dash")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Donchian_Lower_100"], name="Donchian 하단(100일)", line=dict(color="#7e57c2", width=1, dash="dash")),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Trailing_Stop"], name="트레일링 스탑", line=dict(color="#ef5350", width=1.5)),
        row=1,
        col=1,
    )

    buy_points = view[view["Buy_Trigger"]]
    fig.add_trace(
        go.Scatter(
            x=buy_points["Date"],
            y=buy_points["Low"] * 0.99,
            mode="markers",
            name="매수 시그널",
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
            name="청산 시그널",
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
        margin=dict(t=60, b=20, r=160, l=40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(150,150,150,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(150,150,150,0.15)")

    return fig

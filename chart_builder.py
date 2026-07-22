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
        row_heights=[2 / 3, 1 / 6, 1 / 6],  # 캔들:거래량:ATR = 4:1:1
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
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["BB_Upper"],
            name="BB",
            legendgroup="BB",
            line=dict(color="rgba(120,144,156,0.3)", width=1),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["BB_Lower"],
            name="BB하단",
            legendgroup="BB",
            showlegend=False,
            line=dict(color="rgba(120,144,156,0.3)", width=1),
            fill="tonexty",
            fillcolor="rgba(120,144,156,0.05)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["BB_Middle"],
            name="BB중심",
            legendgroup="BB",
            showlegend=False,
            line=dict(color="rgba(84,110,122,0.4)", width=1, dash="dash"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["Donchian_Upper_20"],
            name="DC20",
            legendgroup="DC20",
            line=dict(color="#42a5f5", width=1, dash="dot"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["Donchian_Lower_20"],
            name="DC20하단",
            legendgroup="DC20",
            showlegend=False,
            line=dict(color="#42a5f5", width=1, dash="dot"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["Donchian_Upper_100"],
            name="DC100",
            legendgroup="DC100",
            line=dict(color="#7e57c2", width=1, dash="dash"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=view["Date"],
            y=view["Donchian_Lower_100"],
            name="DC100하단",
            legendgroup="DC100",
            showlegend=False,
            line=dict(color="#7e57c2", width=1, dash="dash"),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["Trailing_Stop"], name="손절선", line=dict(color="#ef5350", width=1.5)),
        row=1,
        col=1,
    )

    # Ichimoku Kinko Hyo (일목균형표) — chart-only reference overlay, see signal_engine.calculate_ichimoku.
    # Only the cloud (Senkou A/B) is drawn, colored by 양운(bullish, Senkou A >= B)/음운(bearish) —
    # 전환선/기준선/후행스팬 are still computed in signal_engine (Senkou A needs Tenkan/Kijun) but
    # are not plotted, per request to keep the chart to just the bullish/bearish cloud read.
    # Extended `displacement` business days past the last candle, the traditional Ichimoku look.
    # Senkou_A/B columns are already displaced (shift(+displacement)) so they cover the historical
    # portion; the tail of the "_Raw" (undisplaced) columns supplies the future-projecting tip,
    # continuing the same series with no gap (see calculate_ichimoku).
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
        cloud_dates = view["Date"].reset_index(drop=True)
        cloud_a = view["Ichimoku_SenkouA"].reset_index(drop=True)
        cloud_b = view["Ichimoku_SenkouB"].reset_index(drop=True)

    # Plotly can't conditionally color a single trace's fill, so the cloud is split into
    # contiguous 양운/음운 runs (by sign of Senkou A - B) and drawn as one filled trace per run —
    # each segment includes its follow-up point too, so adjacent segments join with no visual gap.
    bullish_mask = cloud_a >= cloud_b
    CLOUD_COLORS = {
        True: {"label": "양운", "line": "rgba(239,83,80,0.55)", "fill": "rgba(239,83,80,0.15)"},
        False: {"label": "음운", "line": "rgba(66,165,245,0.55)", "fill": "rgba(66,165,245,0.15)"},
    }
    shown_cloud_labels: set[bool] = set()
    seg_start = 0
    for i in range(1, len(bullish_mask) + 1):
        if i == len(bullish_mask) or bullish_mask.iloc[i] != bullish_mask.iloc[seg_start]:
            bullish = bool(bullish_mask.iloc[seg_start])
            colors = CLOUD_COLORS[bullish]
            seg = slice(seg_start, min(i + 1, len(bullish_mask)))
            show_this = bullish not in shown_cloud_labels
            shown_cloud_labels.add(bullish)
            fig.add_trace(
                go.Scatter(
                    x=cloud_dates.iloc[seg],
                    y=cloud_a.iloc[seg],
                    name=colors["label"],
                    legendgroup=colors["label"],
                    showlegend=False,
                    line=dict(color=colors["line"], width=1),
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=cloud_dates.iloc[seg],
                    y=cloud_b.iloc[seg],
                    name=colors["label"],
                    legendgroup=colors["label"],
                    showlegend=show_this,
                    line=dict(color=colors["line"], width=1),
                    fill="tonexty",
                    fillcolor=colors["fill"],
                ),
                row=1,
                col=1,
            )
            seg_start = i

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
    fig.add_trace(
        go.Bar(x=view["Date"], y=view["Volume"], name="거래량", marker_color=volume_colors, showlegend=False),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(x=view["Date"], y=view["ATR"], name="ATR", line=dict(color="#ffa726", width=1.5), showlegend=False),
        row=3,
        col=1,
    )

    fig.update_layout(
        height=1020,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        template="plotly_white",
        font=dict(family=FONT_FAMILY),
        # Horizontal legend below the chart (not a fixed-width column on the right) so the
        # plot area itself doesn't get squeezed narrow on mobile screens. Only the overlays
        # that actually need distinguishing get a legend entry — 가격/거래량/ATR are already
        # self-evident from their own (sub)plot, and BB/DC20/DC100's upper+lower pairs are
        # grouped under one shared entry (legendgroup) so clicking it toggles both lines.
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.06,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(0,0,0,0)",
            groupclick="togglegroup",
        ),
        margin=dict(t=60, b=90, r=40, l=40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(150,150,150,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(150,150,150,0.15)")

    return fig

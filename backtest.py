"""Triple-Barrier backtest of signal_engine's mechanical 매수/HOLD/매도 rules — see
triple_barrier_backtest_spec.md for the full design. Answers "how often did a 매수 signal
actually lead to a rise (vs. fall vs. flat) within the next `horizon_days`?" using the same
rules the live system uses, not a separate re-implementation.

Manual/local script, not part of collect.yml/recommend.yml (see the spec's section 6) —
run this by hand when you want backtest numbers, it's not a standing service.
"""
from __future__ import annotations

import os

import pandas as pd

import data_fetcher
import signal_engine

BACKTEST_CACHE_DIR = "backtest_cache"
ANALYSIS_START = "2014-09-17"  # BTC-USD's own first trading day (see spec section 3)
FETCH_START = "2014-06-01"  # warm-up margin for Donchian-100/ATR-14/Ichimoku before ANALYSIS_START


def fetch_backtest_history(tickers: list[str], force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Per ticker: full history from FETCH_START to today, cached locally as parquet so
    repeated runs don't re-hit yfinance. `force_refresh=True` re-downloads regardless."""
    os.makedirs(BACKTEST_CACHE_DIR, exist_ok=True)
    history = {}
    for ticker in tickers:
        cache_path = os.path.join(BACKTEST_CACHE_DIR, f"{ticker}.parquet")
        if not force_refresh and os.path.exists(cache_path):
            history[ticker] = pd.read_parquet(cache_path)
            continue
        raw_df = data_fetcher.fetch_ohlcv(ticker, start=FETCH_START)
        if raw_df.empty:
            continue
        raw_df.to_parquet(cache_path, index=False)
        history[ticker] = raw_df
    return history


def compute_triple_barrier_labels(
    df: pd.DataFrame,
    upper_pct: float = 0.10,
    lower_pct: float = 0.10,
    horizon_days: int = 63,
) -> pd.DataFrame:
    """Adds `label` (+1/-1/0/None) and `touch_date` to a copy of df (Date/Open/High/Low/Close,
    sorted by Date). For each day t: upper barrier = Close[t]*(1+upper_pct), lower barrier =
    Close[t]*(1-lower_pct), vertical barrier = t + horizon_days trading days. Scans t+1..vertical
    barrier in order for the first day High touches the upper barrier or Low touches the lower
    barrier; if both trigger the same day, -1 wins (can't tell from daily bars which was hit
    intraday first, and assuming the worse outcome is the conservative choice). label=0 if
    neither barrier is touched by the vertical barrier. label=None ("not yet resolved") for
    the last horizon_days rows, which don't have horizon_days of future data yet -- these are
    excluded from hit-rate stats rather than forced to 0, so "unresolved" isn't conflated with
    "genuinely flat" (see spec section 2).
    """
    out = df.sort_values("Date").reset_index(drop=True).copy()
    n = len(out)
    closes = out["Close"].to_numpy()
    highs = out["High"].to_numpy()
    lows = out["Low"].to_numpy()
    dates = out["Date"].to_numpy()

    labels: list[float | None] = [None] * n
    touch_dates: list = [None] * n

    for t in range(n):
        window_end = min(t + horizon_days, n - 1)
        if window_end <= t or window_end - t < horizon_days:
            continue  # not enough future data yet -- stays None

        upper = closes[t] * (1 + upper_pct)
        lower = closes[t] * (1 - lower_pct)
        label = 0
        touch_date = None
        for j in range(t + 1, window_end + 1):
            hit_upper = highs[j] >= upper
            hit_lower = lows[j] <= lower
            if hit_upper and hit_lower:
                label, touch_date = -1, dates[j]
                break
            if hit_lower:
                label, touch_date = -1, dates[j]
                break
            if hit_upper:
                label, touch_date = 1, dates[j]
                break
        labels[t] = label
        touch_dates[t] = touch_date

    out["label"] = labels
    out["touch_date"] = touch_dates
    return out


def run_backtest(tickers: dict | None = None) -> pd.DataFrame:
    """tickers defaults to data_fetcher.ASSET_CLASS_TICKERS. Combines fetch_backtest_history +
    signal_engine.compute_signals/get_mechanical_action (the same rules the live system uses)
    + compute_triple_barrier_labels into one (ticker, date, action, label, touch_date)
    DataFrame, one row per ticker per trading day from ANALYSIS_START onward (rows before that
    are warm-up only, excluded from the result).
    """
    tickers = tickers if tickers is not None else data_fetcher.ASSET_CLASS_TICKERS
    raw_history = fetch_backtest_history(list(tickers))

    rows = []
    for ticker, raw_df in raw_history.items():
        signals = signal_engine.compute_signals(raw_df)
        labeled = compute_triple_barrier_labels(signals[["Date", "Open", "High", "Low", "Close"]])

        actions = [
            signal_engine.get_mechanical_action(
                {
                    "breakout_20": bool(row.Breakout_20),
                    "breakout_100": bool(row.Breakout_100),
                    "exit_signal": bool(row.Exit_Signal),
                }
            )
            for row in signals.itertuples()
        ]

        merged = pd.DataFrame(
            {
                "ticker": ticker,
                "date": signals["Date"].values,
                "action": actions,
                "label": labeled["label"].values,
                "touch_date": labeled["touch_date"].values,
            }
        )
        rows.append(merged[merged["date"] >= pd.Timestamp(ANALYSIS_START)])

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["ticker", "date", "action", "label", "touch_date"]
    )


_LABEL_NAME = {1: "상승", -1: "하락", 0: "보합"}


def summarize_hit_rates(results: pd.DataFrame) -> pd.DataFrame:
    """액션(매수/HOLD/매도) x 라벨(상승/보합/하락) cross-tab, both combined-across-tickers and
    per-ticker (label=None rows -- not yet resolved -- excluded). Returns counts and % per
    (scope, action) row.
    """
    resolved = results.dropna(subset=["label"]).copy()
    resolved["label_name"] = resolved["label"].map(_LABEL_NAME)

    def _summarize(df: pd.DataFrame, scope: str) -> pd.DataFrame:
        counts = df.groupby(["action", "label_name"]).size().unstack(fill_value=0)
        for name in _LABEL_NAME.values():
            if name not in counts.columns:
                counts[name] = 0
        counts = counts[[_LABEL_NAME[1], _LABEL_NAME[0], _LABEL_NAME[-1]]]
        pct = counts.div(counts.sum(axis=1), axis=0) * 100
        out = counts.copy()
        for col in counts.columns:
            out[f"{col}_pct"] = pct[col].round(1)
        out.insert(0, "scope", scope)
        out.index.name = "action"
        return out.reset_index()

    parts = [_summarize(resolved, "전체")]
    for ticker, group in resolved.groupby("ticker"):
        parts.append(_summarize(group, ticker))
    return pd.concat(parts, ignore_index=True)


if __name__ == "__main__":
    results = run_backtest()
    summary = summarize_hit_rates(results)
    out_path = os.path.join(BACKTEST_CACHE_DIR, "hit_rates_summary.csv")
    os.makedirs(BACKTEST_CACHE_DIR, exist_ok=True)
    summary.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"\nsaved to: {out_path}")

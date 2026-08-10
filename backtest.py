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

import config
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


def simulate_trades(tickers: dict | None = None) -> pd.DataFrame:
    """Literal simulation of the mechanical rule as an actual trading sequence, rather than
    Triple-Barrier's fixed-horizon statistical check: enter at the close on each `Buy_Trigger`
    (first day of a new breakout, signal_engine's first-occurrence-only column -- same one the
    charts use for entry arrows) and exit at the close on the next `Sell_Trigger` (first day
    the trailing stop is breached). One position at a time per ticker -- a `Buy_Trigger` that
    fires while already holding (e.g. a pullback-then-new-high without an intervening exit)
    is ignored rather than pyramiding, matching this project's existing "no partial scale-in/
    out" stance (see paper_trading_spec's exclusions). This also sidesteps the
    Triple-Barrier method's correlated-sampling issue (consecutive 매수-labeled days from the
    same breakout counted as independent trades) since each streak only produces one trade.

    A position still open at the end of available history (entered but no Sell_Trigger yet)
    is excluded from the returned trades -- its outcome isn't known yet, same "don't force an
    unresolved reading" principle as compute_triple_barrier_labels' label=None.
    """
    tickers = tickers if tickers is not None else data_fetcher.ASSET_CLASS_TICKERS
    raw_history = fetch_backtest_history(list(tickers))

    trades = []
    for ticker, raw_df in raw_history.items():
        signals = signal_engine.compute_signals(raw_df)
        signals = signals[signals["Date"] >= pd.Timestamp(ANALYSIS_START)].reset_index(drop=True)

        entry = None
        for row in signals.itertuples():
            if row.Buy_Trigger and entry is None:
                entry = row
            elif row.Sell_Trigger and entry is not None:
                trades.append(
                    {
                        "ticker": ticker,
                        "entry_date": entry.Date,
                        "entry_price": entry.Close,
                        "entry_atr": entry.ATR,  # ATR *at entry* -- what an ATR-sized position would size off of
                        "exit_date": row.Date,
                        "exit_price": row.Close,
                        "return_pct": (row.Close / entry.Close - 1) * 100,
                        "holding_days": (row.Date - entry.Date).days,
                    }
                )
                entry = None

    return pd.DataFrame(trades)


def summarize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker + combined trade stats: count, win rate, mean/median/min/max return %,
    mean holding period. Empty per-ticker groups just don't produce a row.
    """
    def _summarize(df: pd.DataFrame, scope: str) -> dict:
        return {
            "scope": scope,
            "n_trades": len(df),
            "win_rate_pct": round((df["return_pct"] > 0).mean() * 100, 1),
            "avg_return_pct": round(df["return_pct"].mean(), 2),
            "median_return_pct": round(df["return_pct"].median(), 2),
            "max_return_pct": round(df["return_pct"].max(), 2),
            "min_return_pct": round(df["return_pct"].min(), 2),
            "avg_holding_days": round(df["holding_days"].mean(), 1),
        }

    if trades.empty:
        return pd.DataFrame(
            columns=["scope", "n_trades", "win_rate_pct", "avg_return_pct", "median_return_pct", "max_return_pct", "min_return_pct", "avg_holding_days"]
        )

    rows = [_summarize(trades, "전체")]
    for ticker, group in trades.groupby("ticker"):
        rows.append(_summarize(group, ticker))
    return pd.DataFrame(rows)


def calculate_kelly_fraction(trades: pd.DataFrame) -> dict:
    """Kelly criterion optimal risk fraction from this system's own empirical trade stats:
    f* = W - (1-W)/R, where W = win rate and R = avg win % / avg loss % (payoff ratio).
    f* is the fraction of capital Kelly says to risk per trade to maximize long-run
    geometric growth. Full Kelly is high-variance in practice (brutal drawdowns), so
    half-Kelly (f*/2) -- the commonly used, gentler figure -- is returned alongside it,
    not as a replacement.

    Returns None values if there aren't both winning and losing trades to compute from.
    """
    if trades.empty:
        return {k: None for k in ("win_rate_pct", "avg_win_pct", "avg_loss_pct", "payoff_ratio", "kelly_fraction_pct", "half_kelly_fraction_pct")}

    wins = trades.loc[trades["return_pct"] > 0, "return_pct"]
    losses = trades.loc[trades["return_pct"] <= 0, "return_pct"]
    if wins.empty or losses.empty:
        return {k: None for k in ("win_rate_pct", "avg_win_pct", "avg_loss_pct", "payoff_ratio", "kelly_fraction_pct", "half_kelly_fraction_pct")}

    win_rate = len(wins) / len(trades)
    avg_win = wins.mean()
    avg_loss = abs(losses.mean())
    payoff_ratio = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / payoff_ratio

    return {
        "win_rate_pct": round(win_rate * 100, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 2),
        "kelly_fraction_pct": round(kelly * 100, 2),
        "half_kelly_fraction_pct": round(kelly * 50, 2),
    }


def simulate_equity_curve(
    tickers: dict | None = None,
    starting_equity: float = 10000.0,
    risk_pct: float = config.DEFAULT_RISK_PCT,
) -> tuple[pd.DataFrame, dict]:
    """Extends simulate_trades with signal_engine.calculate_position_size -- the same
    ATR-based sizing (shares such that a 3xATR stop-out risks at most `risk_pct` of
    equity) production actually uses -- to track real account equity trade-by-trade,
    instead of just each trade's price return_pct in isolation.

    `risk_pct` can be config.DEFAULT_RISK_PCT (production's default, 1%) or a value from
    calculate_kelly_fraction (full or half) to see how Kelly-derived sizing would have
    compounded instead. Note this is a practical bridge, not an exact Kelly simulation --
    Kelly's f* assumes each bet risks/wins exactly the empirical avg_loss/avg_win, while
    ATR sizing bounds *worst-case* risk per trade (a 3xATR stop) and the realized P&L
    still varies trade to trade -- this is the same heuristic combination of volatility-
    based sizing with a Kelly-derived risk fraction used in standard position-sizing
    practice (e.g. Van Tharp), not a claim that ATR sizing reproduces Kelly's assumptions
    exactly.

    Trades across all tickers are processed in chronological order against one shared
    equity pool. This does NOT model overlapping positions splitting capital -- each
    trade sizes off whatever the *current* equity is, as if it were the only open
    position. Fine for a single-ticker run (no overlap possible); a known simplification
    if scaled to multiple tickers with real overlapping holding periods.

    Returns (per-trade DataFrame with shares/pnl/equity_after columns appended, summary
    dict with ending_equity/total_return_pct/max_drawdown_pct).
    """
    trades = simulate_trades(tickers)
    if trades.empty:
        return trades, {"ending_equity": starting_equity, "total_return_pct": 0.0, "max_drawdown_pct": 0.0}

    trades = trades.sort_values("entry_date").reset_index(drop=True)

    equity = starting_equity
    peak = starting_equity
    max_drawdown_pct = 0.0
    shares_list, pnl_list, equity_after_list = [], [], []

    for row in trades.itertuples():
        shares = signal_engine.calculate_position_size(equity, row.entry_atr, risk_pct)
        pnl = shares * (row.exit_price - row.entry_price)
        equity += pnl
        peak = max(peak, equity)
        drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        shares_list.append(shares)
        pnl_list.append(round(pnl, 2))
        equity_after_list.append(round(equity, 2))

    trades = trades.copy()
    trades["shares"] = shares_list
    trades["pnl"] = pnl_list
    trades["equity_after"] = equity_after_list

    summary = {
        "starting_equity": starting_equity,
        "ending_equity": round(equity, 2),
        "total_return_pct": round((equity / starting_equity - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
    }
    return trades, summary


if __name__ == "__main__":
    os.makedirs(BACKTEST_CACHE_DIR, exist_ok=True)

    results = run_backtest()
    summary = summarize_hit_rates(results)
    hit_rate_path = os.path.join(BACKTEST_CACHE_DIR, "hit_rates_summary.csv")
    summary.to_csv(hit_rate_path, index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"\nsaved to: {hit_rate_path}")

    trades = simulate_trades()
    trade_summary = summarize_trades(trades)
    trades_path = os.path.join(BACKTEST_CACHE_DIR, "trades.csv")
    trade_summary_path = os.path.join(BACKTEST_CACHE_DIR, "trade_summary.csv")
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    trade_summary.to_csv(trade_summary_path, index=False, encoding="utf-8-sig")
    print()
    print(trade_summary.to_string(index=False))
    print(f"\nsaved to: {trades_path}, {trade_summary_path}")

    kelly = calculate_kelly_fraction(trades)
    print()
    print("Kelly:", kelly)

    default_trades, default_curve_summary = simulate_equity_curve(risk_pct=config.DEFAULT_RISK_PCT)
    print(f"\nEquity curve @ risk_pct={config.DEFAULT_RISK_PCT:.1%} (production default):", default_curve_summary)

    if kelly["half_kelly_fraction_pct"] is not None and kelly["half_kelly_fraction_pct"] > 0:
        half_kelly_risk_pct = kelly["half_kelly_fraction_pct"] / 100
        kelly_trades, kelly_curve_summary = simulate_equity_curve(risk_pct=half_kelly_risk_pct)
        print(f"Equity curve @ risk_pct={half_kelly_risk_pct:.1%} (half-Kelly):", kelly_curve_summary)
        equity_path = os.path.join(BACKTEST_CACHE_DIR, "equity_curve_half_kelly.csv")
        kelly_trades.to_csv(equity_path, index=False, encoding="utf-8-sig")
        print(f"saved to: {equity_path}")
    else:
        default_trades.to_csv(os.path.join(BACKTEST_CACHE_DIR, "equity_curve_default.csv"), index=False, encoding="utf-8-sig")

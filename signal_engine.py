"""Tom Basso style trend-following signal engine: Donchian breakouts, Wilder ATR,
trailing stops, position sizing, and a volume-surge false-breakout filter.

Pure pandas — no Drive/yfinance I/O here. Callers pass in an OHLCV DataFrame with
columns Date, Open, High, Low, Close, Volume (as produced by data_fetcher.fetch_ohlcv
or drive_db.DriveDB.load_ticker).
"""
from __future__ import annotations

import pandas as pd

import config


def calculate_atr(df: pd.DataFrame, window: int = config.ATR_WINDOW) -> pd.Series:
    """14-day Wilder's-smoothed Average True Range."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def calculate_donchian(df: pd.DataFrame, window: int) -> tuple[pd.Series, pd.Series]:
    """N-day Donchian upper/lower bands, excluding today (so a breakout is measurable)."""
    upper = df["High"].shift(1).rolling(window).max()
    lower = df["Low"].shift(1).rolling(window).min()
    return upper, lower


def calculate_trailing_stop(
    df: pd.DataFrame,
    atr: pd.Series,
    window: int = config.DONCHIAN_ENTRY_WINDOW,
    atr_multiplier: float = config.ATR_STOP_MULTIPLIER,
) -> pd.Series:
    """Trailing stop = highest high over `window` days - atr_multiplier * ATR."""
    highest_high = df["High"].rolling(window).max()
    return highest_high - atr_multiplier * atr


def calculate_bollinger_bands(
    df: pd.DataFrame,
    window: int = config.BOLLINGER_WINDOW,
    num_std: float = config.BOLLINGER_NUM_STD,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands: rolling SMA(window) of Close, +/- num_std standard deviations."""
    middle = df["Close"].rolling(window).mean()
    std = df["Close"].rolling(window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def calculate_ichimoku(
    df: pd.DataFrame,
    tenkan_window: int = config.ICHIMOKU_TENKAN_WINDOW,
    kijun_window: int = config.ICHIMOKU_KIJUN_WINDOW,
    senkou_b_window: int = config.ICHIMOKU_SENKOU_B_WINDOW,
    displacement: int = config.ICHIMOKU_DISPLACEMENT,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Ichimoku Kinko Hyo (일목균형표): 전환선(Tenkan)/기준선(Kijun)/구름(Senkou A·B, displacement일
    선행)/후행스팬(Chikou). Chart-only reference overlay — see get_ichimoku_confluence for the
    advisory (never mechanical) use of the cloud position.

    Also returns the pre-displacement Senkou A/B ("_raw") so chart_builder can draw the cloud's
    future-projecting tip past the last candle, the traditional Ichimoku look.
    """
    tenkan = (df["High"].rolling(tenkan_window).max() + df["Low"].rolling(tenkan_window).min()) / 2
    kijun = (df["High"].rolling(kijun_window).max() + df["Low"].rolling(kijun_window).min()) / 2
    senkou_a_raw = (tenkan + kijun) / 2
    senkou_b_raw = (
        df["High"].rolling(senkou_b_window).max() + df["Low"].rolling(senkou_b_window).min()
    ) / 2
    senkou_a = senkou_a_raw.shift(displacement)
    senkou_b = senkou_b_raw.shift(displacement)
    chikou = df["Close"].shift(-displacement)
    return tenkan, kijun, senkou_a, senkou_b, chikou, senkou_a_raw, senkou_b_raw


def calculate_volume_surge(
    df: pd.DataFrame,
    window: int = config.VOLUME_SURGE_WINDOW,
    multiplier: float = config.VOLUME_SURGE_MULTIPLIER,
) -> pd.Series:
    """True where today's volume >= multiplier * average volume of the prior `window` days."""
    avg_volume = df["Volume"].shift(1).rolling(window).mean()
    return df["Volume"] >= multiplier * avg_volume


def calculate_position_size(
    equity: float,
    atr: float,
    risk_pct: float = config.DEFAULT_RISK_PCT,
    atr_multiplier: float = config.ATR_STOP_MULTIPLIER,
) -> int:
    """Shares to buy so that a stop-out risks at most `risk_pct` of `equity`."""
    stop_distance = atr_multiplier * atr
    if pd.isna(stop_distance) or stop_distance <= 0:
        return 0
    return int((equity * risk_pct) // stop_distance)


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add ATR/Donchian/breakout/trailing-stop/volume-surge columns to an OHLCV DataFrame."""
    signals = df.sort_values("Date").reset_index(drop=True).copy()

    signals["ATR"] = calculate_atr(signals)
    signals["Donchian_Upper_20"], signals["Donchian_Lower_20"] = calculate_donchian(
        signals, config.DONCHIAN_ENTRY_WINDOW
    )
    signals["Donchian_Upper_100"], signals["Donchian_Lower_100"] = calculate_donchian(
        signals, config.DONCHIAN_LONG_WINDOW
    )
    signals["Breakout_20"] = signals["Close"] > signals["Donchian_Upper_20"]
    signals["Breakout_100"] = signals["Close"] > signals["Donchian_Upper_100"]

    signals["Trailing_Stop"] = calculate_trailing_stop(signals, signals["ATR"])
    signals["Exit_Signal"] = signals["Close"] < signals["Trailing_Stop"]
    signals["Volume_Surge"] = calculate_volume_surge(signals)
    signals["BB_Middle"], signals["BB_Upper"], signals["BB_Lower"] = calculate_bollinger_bands(signals)
    (
        signals["Ichimoku_Tenkan"],
        signals["Ichimoku_Kijun"],
        signals["Ichimoku_SenkouA"],
        signals["Ichimoku_SenkouB"],
        signals["Ichimoku_Chikou"],
        signals["Ichimoku_SenkouA_Raw"],
        signals["Ichimoku_SenkouB_Raw"],
    ) = calculate_ichimoku(signals)

    # First-occurrence-only versions of the breakout/exit conditions, for marking entry/exit
    # points on a chart without re-marking every subsequent day a sustained trend stays valid.
    any_breakout = signals["Breakout_20"] | signals["Breakout_100"]
    signals["Buy_Trigger"] = any_breakout & ~any_breakout.shift(1, fill_value=False)
    signals["Sell_Trigger"] = signals["Exit_Signal"] & ~signals["Exit_Signal"].shift(1, fill_value=False)

    return signals


def get_latest_signal_summary(
    df: pd.DataFrame, equity: float | None = None, risk_pct: float = config.DEFAULT_RISK_PCT
) -> dict:
    """Today's signal snapshot for one ticker; adds suggested_shares if `equity` is given."""
    signals = compute_signals(df)
    latest = signals.iloc[-1]

    summary = {
        "date": latest["Date"],
        "close": latest["Close"],
        "atr": latest["ATR"],
        "breakout_20": bool(latest["Breakout_20"]),
        "breakout_100": bool(latest["Breakout_100"]),
        "trailing_stop": latest["Trailing_Stop"],
        "exit_signal": bool(latest["Exit_Signal"]),
        "volume_surge": bool(latest["Volume_Surge"]),
        "ichimoku_tenkan": latest["Ichimoku_Tenkan"],
        "ichimoku_kijun": latest["Ichimoku_Kijun"],
        "ichimoku_senkou_a": latest["Ichimoku_SenkouA"],
        "ichimoku_senkou_b": latest["Ichimoku_SenkouB"],
    }
    if equity is not None:
        summary["suggested_shares"] = calculate_position_size(equity, latest["ATR"], risk_pct)
    return summary


def get_mechanical_action(summary: dict) -> str:
    """Deterministic 매수/HOLD/매도 call from the Donchian/trailing-stop rules alone — no
    LLM or news involved. Takes a get_latest_signal_summary() dict. This is the authoritative
    action: an LLM may add commentary, but Tom Basso's system is rule-based, not news-driven,
    so the actual buy/hold/sell call should never depend on a network call succeeding.
    """
    if summary["breakout_20"] or summary["breakout_100"]:
        return "매수"
    if summary["exit_signal"]:
        return "매도"
    return "HOLD"


def get_ichimoku_confluence(summary: dict, action: str) -> dict | None:
    """Advisory-only: does today's Ichimoku cloud position agree with the mechanical
    매수/매도 action? Purely informational context for the recommendation narrative
    (recommendation_engine._build_rule_based_explanation / openrouter_briefing.generate_recommendation)
    — never used to change `action` itself or the position-sizing calculation.

    Returns None if the cloud isn't computable yet (insufficient history, ~78 bars needed).
    """
    senkou_a, senkou_b = summary.get("ichimoku_senkou_a"), summary.get("ichimoku_senkou_b")
    if pd.isna(senkou_a) or pd.isna(senkou_b):
        return None

    cloud_top, cloud_bottom = max(senkou_a, senkou_b), min(senkou_a, senkou_b)
    cloud_bullish = senkou_a >= senkou_b
    price = summary["close"]
    if price > cloud_top:
        position = "above"
    elif price < cloud_bottom:
        position = "below"
    else:
        position = "inside"

    if action == "매수":
        agrees = position == "above" and cloud_bullish
    elif action == "매도":
        agrees = position == "below" and not cloud_bullish
    else:
        agrees = None

    return {"position": position, "cloud_bullish": cloud_bullish, "agrees_with_action": agrees}


def scan_for_signals(
    ticker_data: dict[str, pd.DataFrame],
    equity: float | None = None,
    risk_pct: float = config.DEFAULT_RISK_PCT,
) -> pd.DataFrame:
    """Run get_latest_signal_summary over many tickers; flag+sort by breakout AND volume surge.

    `ticker_data` maps ticker -> OHLCV DataFrame (e.g. from DriveDB.load_ticker per ticker).
    """
    min_rows = max(config.DONCHIAN_LONG_WINDOW, config.ATR_WINDOW) + 1
    rows = []
    for ticker, df in ticker_data.items():
        if df is None or len(df) < min_rows:
            continue
        summary = get_latest_signal_summary(df, equity=equity, risk_pct=risk_pct)
        summary["ticker"] = ticker
        rows.append(summary)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    result["priority"] = (result["breakout_20"] | result["breakout_100"]) & result["volume_surge"]
    return result.sort_values(["priority", "date"], ascending=[False, False]).reset_index(drop=True)

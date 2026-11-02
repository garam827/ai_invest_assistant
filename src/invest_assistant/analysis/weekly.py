"""Weekly aggregation math: NYSE trading calendar, ISO week windows, per-asset weekly stats.

Pure functions — no Drive, network, or LLM. Mechanical actions are never computed here;
the weekly signal grid reads the stored `_signal_history.json` records only.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

import pandas as pd

from invest_assistant.analysis import signals as signal_engine

RISK_TICKERS = ("SPY", "QQQ", "BTC-USD", "ETH-USD")
SAFE_TICKERS = ("TLT", "IEF", "UUP")
REGIMES = ("위험선호", "위험회피", "혼조")


def _easter(year: int) -> datetime.date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime.date:
    first = datetime.date(year, month, 1)
    return first + datetime.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> datetime.date:
    last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return last - datetime.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: datetime.date) -> datetime.date:
    """Saturday holidays close the Friday before, Sunday holidays the Monday after."""
    if day.weekday() == 5:
        return day - datetime.timedelta(days=1)
    if day.weekday() == 6:
        return day + datetime.timedelta(days=1)
    return day


def nyse_holidays(year: int) -> set[datetime.date]:
    """Full-day NYSE closures for `year` (regular rules; ad-hoc closures are not modeled).

    New Year's Day falling on a Saturday is not observed on the prior Friday (NYSE rule),
    so that Friday stays a trading day.
    """
    new_year = datetime.date(year, 1, 1)
    holidays = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter(year) - datetime.timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(datetime.date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(datetime.date(year, 12, 25)),
    }
    if new_year.weekday() != 5:
        holidays.add(_observed(new_year))
    if year >= 2022:
        holidays.add(_observed(datetime.date(year, 6, 19)))
    return holidays


def is_trading_day(day: datetime.date) -> bool:
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


def week_id(day: datetime.date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def parse_week(week: str) -> tuple[datetime.date, datetime.date]:
    """'2026-W44' -> (Monday, Sunday). Raises ValueError on a malformed id."""
    try:
        year_part, week_part = week.split("-W")
        monday = datetime.date.fromisocalendar(int(year_part), int(week_part), 1)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid week {week!r}; expected YYYY-Www (e.g. 2026-W44)") from exc
    if week_id(monday) != week:
        raise ValueError(f"Invalid week {week!r}; expected YYYY-Www (e.g. 2026-W44)")
    return monday, monday + datetime.timedelta(days=6)


def expected_trading_days(week: str) -> list[datetime.date]:
    monday, _ = parse_week(week)
    days = (monday + datetime.timedelta(days=offset) for offset in range(5))
    return [day for day in days if is_trading_day(day)]


def default_target_week(today: datetime.date) -> str:
    """Most recent ISO week whose Saturday has already arrived (US Eastern `today`)."""
    saturday = today - datetime.timedelta(days=(today.weekday() - 5) % 7)
    return week_id(saturday - datetime.timedelta(days=1))


def format_period(days: list[str]) -> str:
    first, last = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    return f"{first.month}/{first.day}~{last.month}/{last.day}"


@dataclass(frozen=True)
class WeekWindow:
    week: str
    trading_days: list[str]  # YYYY-MM-DD, ascending, from the anchor ticker's stored bars
    prev_close_date: str  # last anchor bar before the week

    @property
    def last_day(self) -> str:
        return self.trading_days[-1]

    @property
    def period(self) -> str:
        return format_period(self.trading_days)


def _dates(raw_df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(raw_df["Date"]).dt.strftime("%Y-%m-%d")


def resolve_week_window(week: str, anchor_df: pd.DataFrame) -> WeekWindow:
    """Trading days come from the anchor (SPY) bars inside the ISO week, so holiday-shortened
    weeks need no special casing. Raises RuntimeError when the week has no bars yet."""
    monday, sunday = parse_week(week)
    dates = sorted(set(_dates(anchor_df)))
    days = [d for d in dates if monday.isoformat() <= d <= sunday.isoformat()]
    if not days:
        raise RuntimeError(f"No SPY bars stored for {week}; collection has not covered this week")
    prior = [d for d in dates if d < monday.isoformat()]
    if not prior:
        raise RuntimeError(f"No SPY bar before {week} to measure the weekly return from")
    return WeekWindow(week=week, trading_days=days, prev_close_date=prior[-1])


def check_freshness(
    window: WeekWindow, frames: dict[str, pd.DataFrame], history: dict, strict: bool
) -> list[str]:
    """Fail before publication when the week's data is incomplete.

    Always: every ticker needs a bar on the week's last trading day. `strict` (the scheduled
    run): the stored trading days must match the NYSE calendar and the signal history must
    hold every ticker for the final day. Returns non-fatal warnings for `--week` reruns.
    """
    problems = [t for t, df in frames.items() if window.last_day not in set(_dates(df))]
    if problems:
        raise RuntimeError(
            f"Stale weekly data for {window.week}: no {window.last_day} bar for {', '.join(sorted(problems))}"
        )
    expected = [d.isoformat() for d in expected_trading_days(window.week)]
    warnings = []
    if window.trading_days != expected:
        message = f"{window.week} stored trading days {window.trading_days} != NYSE calendar {expected}"
        if strict:
            raise RuntimeError(f"Stale weekly data: {message}")
        warnings.append(message)
    missing_history = sorted(set(frames) - set(history.get(window.last_day, {})))
    if missing_history:
        message = f"signal history for {window.last_day} lacks {', '.join(missing_history)}"
        if strict:
            raise RuntimeError(f"Stale weekly data: {message}")
        warnings.append(message)
    return warnings


def compute_asset_week(raw_df: pd.DataFrame, window: WeekWindow) -> dict:
    """Weekly stats on US trading-day closes (crypto weekend bars are excluded from the
    high/low and return endpoints so every asset is measured over the same days).

    Stop/DC20 distances come from signal_engine.compute_signals on bars up to the week's
    last trading day — informational distances, not a new action.
    """
    df = raw_df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Date"] <= pd.Timestamp(window.last_day)].sort_values("Date").reset_index(drop=True)
    day_keys = df["Date"].dt.strftime("%Y-%m-%d")

    week_bars = df[day_keys.isin(window.trading_days)]
    prior_bars = df[day_keys <= window.prev_close_date]
    if week_bars.empty or prior_bars.empty:
        raise RuntimeError(f"Missing bars to compute {window.week} weekly stats")

    prev_close = float(prior_bars["Close"].iloc[-1])
    close = float(week_bars["Close"].iloc[-1])
    latest = signal_engine.compute_signals(df).iloc[-1]
    stop = latest["Trailing_Stop"]
    dc20 = latest["Donchian_Upper_20"]
    return {
        "prev_close": prev_close,
        "close": close,
        "return_pct": (close / prev_close - 1) * 100,
        "high": float(week_bars["High"].max()),
        "low": float(week_bars["Low"].min()),
        "trailing_stop": None if pd.isna(stop) else float(stop),
        "stop_distance_pct": None if pd.isna(stop) else (close - float(stop)) / close * 100,
        "dc20_upper": None if pd.isna(dc20) else float(dc20),
        "dc20_distance_pct": None if pd.isna(dc20) else (float(dc20) / close - 1) * 100,
    }


def week_signal_grid(history: dict, window: WeekWindow, tickers) -> dict[str, dict[str, str | None]]:
    """{date: {ticker: stored action or None}} for the week's trading days — records only."""
    return {day: {t: history.get(day, {}).get(t) for t in tickers} for day in window.trading_days}


def signal_changes(
    grid: dict[str, dict[str, str | None]], prev_actions: dict[str, str] | None = None
) -> dict[str, list[tuple[str, str, str]]]:
    """Tickers whose stored action changed during the week -> [(date, from, to), ...].

    Stored actions persist while their condition holds (a ticker below its stop records 매도
    every day), so a change is a transition between consecutive recorded days, starting from
    the prior week's last day (`prev_actions`). Days without a record are skipped, not
    treated as a change."""
    changes: dict[str, list[tuple[str, str, str]]] = {}
    last = dict(prev_actions or {})
    for day in sorted(grid):
        for ticker, action in grid[day].items():
            if action is None:
                continue
            previous = last.get(ticker)
            if previous is not None and previous != action:
                changes.setdefault(ticker, []).append((day, previous, action))
            last[ticker] = action
    return changes


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def rule_based_regime(stats: dict[str, dict]) -> tuple[str, float | None, float | None]:
    """Risk-on/off read from weekly returns only (advisory; never feeds an action)."""
    risk = _average([stats[t]["return_pct"] for t in RISK_TICKERS if t in stats])
    safe = _average([stats[t]["return_pct"] for t in SAFE_TICKERS if t in stats])
    if risk is not None and safe is not None:
        if risk > 0 and safe <= 0:
            return "위험선호", risk, safe
        if risk < 0 and safe >= 0:
            return "위험회피", risk, safe
    return "혼조", risk, safe


def macro_week_change(closes: pd.Series, window: WeekWindow) -> dict | None:
    """Prior-week close -> week-end close for one macro series (index: YYYY-MM-DD dates)."""
    series = closes.dropna().sort_index()
    start = series[series.index <= window.prev_close_date]
    end = series[series.index <= window.last_day]
    end = end[end.index >= window.trading_days[0]]
    if start.empty or end.empty:
        return None
    return {
        "start_value": float(start.iloc[-1]),
        "start_date": start.index[-1],
        "end_value": float(end.iloc[-1]),
        "end_date": end.index[-1],
    }

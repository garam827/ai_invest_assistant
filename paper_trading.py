"""Manual paper trading (모의 투자, forward-testing) — see paper_trading_spec.md.

Positions are recorded by the user (Streamlit UI only — the cron pipeline is read-only,
see the spec's "핵심 설계 결정") and their P&L is computed from data already collected
daily by data_fetcher — no new external API calls (yfinance/Exa/OpenRouter) here.

Persisted to Drive as one JSON file (PAPER_TRADES_FILENAME), same DriveDB.load_json/
save_json mechanism already used for _universe.json/_recommendations_{date}.json.
"""
from __future__ import annotations

import uuid

import pandas as pd

PAPER_TRADES_FILENAME = "_paper_trades.json"


def load_positions(drive_db) -> list[dict]:
    data = drive_db.load_json(PAPER_TRADES_FILENAME)
    return (data or {}).get("positions", [])


def save_positions(drive_db, positions: list[dict]) -> None:
    drive_db.save_json(PAPER_TRADES_FILENAME, {"positions": positions})


def _price_on_or_before(df: pd.DataFrame, date: str) -> float | None:
    """Close price on `date`, or the nearest prior trading day's close if `date` itself
    has no bar (e.g. a weekend/holiday pick) — mirrors how a real market order placed on
    a non-trading day would actually fill on the next available session's terms."""
    if df is None or df.empty:
        return None
    eligible = df[pd.to_datetime(df["Date"]) <= pd.to_datetime(date)]
    if eligible.empty:
        return None
    return float(eligible.sort_values("Date").iloc[-1]["Close"])


def preview_price(drive_db, ticker: str, date: str) -> float | None:
    """Public wrapper around the entry/exit price lookup, for a UI to show a suggested
    price before the user actually commits to opening/closing a position."""
    return _price_on_or_before(drive_db.load_ticker(ticker), date)


def open_position(
    drive_db,
    ticker: str,
    entry_date: str,
    quantity: float,
    entry_price: float | None = None,
) -> dict:
    """Record a new open position. entry_price=None auto-fills from entry_date's actual
    close (drive_db.load_ticker) — "종가에 매수했다"는 스펙 요구사항의 기본 동작."""
    if entry_price is None:
        entry_price = _price_on_or_before(drive_db.load_ticker(ticker), entry_date)
        if entry_price is None:
            raise ValueError(f"{ticker}: no price data available on or before {entry_date}")

    position = {
        "id": uuid.uuid4().hex[:8],
        "ticker": ticker,
        "quantity": quantity,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "status": "open",
        "exit_date": None,
        "exit_price": None,
        "note": "",
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    positions = load_positions(drive_db)
    positions.append(position)
    save_positions(drive_db, positions)
    return position


def close_position(
    drive_db,
    position_id: str,
    exit_date: str | None = None,
    exit_price: float | None = None,
) -> dict:
    """Close an existing open position. exit_date=None -> today. exit_price=None -> the
    ticker's latest stored close."""
    positions = load_positions(drive_db)
    for position in positions:
        if position["id"] == position_id:
            break
    else:
        raise ValueError(f"No position with id {position_id}")
    if position["status"] != "open":
        raise ValueError(f"Position {position_id} is already closed")

    exit_date = exit_date or pd.Timestamp.now(tz="UTC").date().isoformat()
    if exit_price is None:
        exit_price = _price_on_or_before(drive_db.load_ticker(position["ticker"]), exit_date)
        if exit_price is None:
            raise ValueError(f"{position['ticker']}: no price data available on or before {exit_date}")

    position["status"] = "closed"
    position["exit_date"] = exit_date
    position["exit_price"] = exit_price
    save_positions(drive_db, positions)
    return position


def compute_position_returns(drive_db, positions: list[dict]) -> list[dict]:
    """Adds current_price/unrealized_pnl/unrealized_pnl_pct (open positions) or
    realized_pnl/realized_pnl_pct (closed) to a copy of each position dict. Never raises —
    current_price is left None if the ticker's data can't be found, matching the rest of
    the codebase's "one bad lookup shouldn't break the whole batch" principle.
    """
    enriched = []
    for position in positions:
        position = dict(position)
        if position["status"] == "open":
            current_price = _price_on_or_before(
                drive_db.load_ticker(position["ticker"]), pd.Timestamp.now(tz="UTC").date().isoformat()
            )
            position["current_price"] = current_price
            if current_price is not None:
                position["unrealized_pnl"] = (current_price - position["entry_price"]) * position["quantity"]
                position["unrealized_pnl_pct"] = (current_price - position["entry_price"]) / position["entry_price"] * 100
            else:
                position["unrealized_pnl"] = None
                position["unrealized_pnl_pct"] = None
        else:
            position["realized_pnl"] = (position["exit_price"] - position["entry_price"]) * position["quantity"]
            position["realized_pnl_pct"] = (position["exit_price"] - position["entry_price"]) / position["entry_price"] * 100
        enriched.append(position)
    return enriched

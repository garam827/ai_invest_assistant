from __future__ import annotations

import pandas as pd
import streamlit as st

from invest_assistant.portfolio import paper as paper_trading
from invest_assistant.recommendations import engine as recommendation_engine
from invest_assistant.storage import reports as report_store
from invest_assistant.storage.drive import DriveDB
from invest_assistant.universe import UNIVERSE_FILENAME


@st.cache_resource
def get_drive_db() -> DriveDB:
    return DriveDB()

@st.cache_data(ttl=3600, show_spinner="Drive에서 종목 목록 불러오는 중...")
def get_universe() -> dict:
    db = get_drive_db()
    universe = db.load_json(UNIVERSE_FILENAME)
    if not universe:
        return {"tickers": sorted(db.list_tickers()), "sectors": {}, "descriptions": {}}
    tickers = sorted(universe.get("active_tickers") or db.list_tickers())
    return {
        "tickers": tickers,
        "sectors": universe.get("sectors", {}),
        "descriptions": universe.get("descriptions", {}),
    }

@st.cache_data(ttl=3600, show_spinner="Drive에서 시세 불러오는 중...")
def load_ticker_data(ticker: str) -> pd.DataFrame | None:
    return get_drive_db().load_ticker(ticker)

@st.cache_data(ttl=86400, show_spinner="뉴스 수집 및 분석 중...")
def get_recommendation(ticker: str, latest_date: str, use_llm: bool) -> dict:
    """Cached by (ticker, latest bar date, use_llm) — LLM/news calls only happen once per new
    trading day per ticker, not on every rerun/tab-switch (st.tabs bodies all execute every
    rerun). Delegates to recommendation_engine so the cron job (recommendation_engine.py) and
    this UI share the exact same logic. `use_llm` is config.STREAMLIT_ENABLE_LLM — see
    render_ticker_chart for the button gate that guards the news call itself when it's off.
    """
    return recommendation_engine.get_recommendation_for_ticker(get_drive_db(), ticker, use_llm=use_llm)

@st.cache_data(ttl=3600, show_spinner="리포트 목록 불러오는 중...")
def get_report_dates() -> list[str]:
    return report_store.list_report_dates(get_drive_db())

@st.cache_data(ttl=300, show_spinner="테스트 리포트 목록 불러오는 중...")
def get_test_report_dates() -> list[str]:
    """Short TTL — unlike real reports (one per day), test dates can be created/re-run
    within the same session while someone is actively testing the pipeline."""
    return report_store.list_test_report_dates(get_drive_db())

@st.cache_data(ttl=86400, show_spinner="리포트 불러오는 중...")
def get_report_html(date: str) -> str | None:
    """Cached by date, not TTL alone — a past date's report never changes once published."""
    return report_store.load_report(get_drive_db(), date)

@st.cache_data(ttl=3600, show_spinner=False)
def get_signal_history() -> dict:
    """{date: {ticker: action}} — one Drive read for the whole report-history table's
    action columns, instead of one _recommendations_{date}.json read per row."""
    return recommendation_engine.load_signal_history(get_drive_db())

@st.cache_data(ttl=300, show_spinner="포지션 불러오는 중...")
def get_paper_positions() -> list[dict]:
    """Short TTL since positions can change within a session — any open/close action also
    calls .clear() right after the Drive write succeeds (see the 모의 투자 tab below)."""
    db = get_drive_db()
    return paper_trading.compute_position_returns(db, paper_trading.load_positions(db))

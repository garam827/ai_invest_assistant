from __future__ import annotations

import streamlit as st

from apps.streamlit.components.ticker_chart import render_ticker_chart
from apps.streamlit.constants import (
    ALL_SECTORS_LABEL,
    DEFAULT_PERIOD_LABEL,
    PERIOD_OPTIONS,
)
from apps.streamlit.services import get_universe


def render():
    st.header("종목별 시그널 차트 (S&P 500)")

    universe = get_universe()
    all_tickers = universe["tickers"]
    sector_map = universe["sectors"]
    description_map = universe["descriptions"]

    if not all_tickers:
        st.warning("Drive에 저장된 종목이 없습니다. '데이터 적재' 탭에서 먼저 데이터를 적재해주세요.")
    else:
        if "selected_sp500_ticker" not in st.session_state:
            st.session_state.selected_sp500_ticker = None
            st.session_state.selected_sp500_period = DEFAULT_PERIOD_LABEL

        # 섹터 선택은 폼 밖에 둬서 클릭 즉시 종목 드롭다운을 좁혀준다 (차트 재계산은 아직 안 함).
        sector_options = [ALL_SECTORS_LABEL] + sorted(set(sector_map.values())) if sector_map else [ALL_SECTORS_LABEL]
        sector = st.selectbox("섹터/테마", sector_options, key="sp500_sector_select")
        filtered_tickers = all_tickers if sector == ALL_SECTORS_LABEL else [t for t in all_tickers if sector_map.get(t) == sector]

        with st.form("sp500_controls"):
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                ticker = col1.selectbox(f"종목 선택 ({len(filtered_tickers)}개)", filtered_tickers, key="sp500_ticker_select")
            with col2:
                period_label = col2.selectbox(
                    "표시 기간",
                    list(PERIOD_OPTIONS.keys()),
                    index=list(PERIOD_OPTIONS).index(DEFAULT_PERIOD_LABEL),
                    key="sp500_period_select",
                )
            with col3:
                st.write("")
                submitted = st.form_submit_button("조회", type="primary", width="stretch")

        if submitted:
            st.session_state.selected_sp500_ticker = ticker
            st.session_state.selected_sp500_period = period_label

        if st.session_state.selected_sp500_ticker is None:
            st.info("섹터 → 종목 → 기간을 선택하고 '조회'를 눌러주세요.")
        else:
            active_ticker = st.session_state.selected_sp500_ticker
            subtitle = description_map.get(active_ticker) or sector_map.get(active_ticker, "")
            render_ticker_chart(
                active_ticker,
                st.session_state.selected_sp500_period,
                subtitle=subtitle,
                key_prefix="sp500",
            )

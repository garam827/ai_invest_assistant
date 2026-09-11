from __future__ import annotations

import streamlit as st

from apps.streamlit.components.ticker_chart import render_ticker_chart
from apps.streamlit.constants import DEFAULT_PERIOD_LABEL, PERIOD_OPTIONS
from invest_assistant import universe as instrument_universe


def render():
    st.header("대표 자산군별 추세추종 분석")
    st.caption("S&P 500·비트코인·금·미국 국채·원자재(원유/천연가스/농산물/구리 등)를 유동성 높은 ETF(또는 현물)로 대신 추적해 동일한 Donchian/ATR 규칙을 적용합니다.")

    if "selected_asset_ticker" not in st.session_state:
        st.session_state.selected_asset_ticker = None
        st.session_state.selected_asset_period = DEFAULT_PERIOD_LABEL

    # 카테고리 선택은 폼 밖에 둬서 클릭 즉시 세부 종목 드롭다운을 좁혀준다 (탭2의 섹터 필터와 동일 패턴).
    asset_categories = sorted({info["category"] for info in instrument_universe.ASSET_CLASS_TICKERS.values()})
    asset_category = st.selectbox("자산군 카테고리", asset_categories, key="asset_category_select")
    filtered_assets = [
        (ticker, info["label"]) for ticker, info in instrument_universe.ASSET_CLASS_TICKERS.items() if info["category"] == asset_category
    ]
    asset_label_to_ticker = {label: ticker for ticker, label in filtered_assets}

    with st.form("asset_controls"):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            asset_label = col1.selectbox(f"세부 종목 ({len(filtered_assets)}개)", list(asset_label_to_ticker), key="asset_label_select")
        with col2:
            asset_period_label = col2.selectbox(
                "표시 기간",
                list(PERIOD_OPTIONS.keys()),
                index=list(PERIOD_OPTIONS).index(DEFAULT_PERIOD_LABEL),
                key="asset_period_select",
            )
        with col3:
            st.write("")
            asset_submitted = st.form_submit_button("조회", type="primary", width="stretch")

    if asset_submitted:
        st.session_state.selected_asset_ticker = asset_label_to_ticker[asset_label]
        st.session_state.selected_asset_period = asset_period_label

    if st.session_state.selected_asset_ticker is None:
        st.info("자산군 카테고리 → 세부 종목 → 기간을 선택하고 '조회'를 눌러주세요.")
    else:
        active_asset_ticker = st.session_state.selected_asset_ticker
        asset_info = instrument_universe.ASSET_CLASS_TICKERS[active_asset_ticker]
        render_ticker_chart(
            active_asset_ticker,
            st.session_state.selected_asset_period,
            subtitle=f"{asset_info['label']} — {asset_info['description']}",
            key_prefix="asset",
        )

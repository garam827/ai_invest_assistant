"""Streamlit dashboard: one page with six tabs."""
import streamlit as st

from apps.streamlit.tabs import (
    asset_classes,
    collection,
    introduction,
    paper_trading,
    reports,
    stocks,
)

st.set_page_config(page_title="추세추종 투자 어시스턴트", layout="wide")

tab_intro, tab_asset, tab_sp500, tab_collect, tab_report, tab_paper = st.tabs(
    ["소개", "대표 자산군 분석", "종목 차트 (S&P 500)", "데이터 적재", "리포트 히스토리", "모의 투자"]
)

with tab_intro:
    introduction.render()

with tab_asset:
    asset_classes.render()

with tab_sp500:
    stocks.render()

with tab_collect:
    collection.render()

with tab_report:
    reports.render()

with tab_paper:
    paper_trading.render()

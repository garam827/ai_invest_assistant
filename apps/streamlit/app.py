"""Streamlit dashboard: one page with six tabs."""
import streamlit as st

from apps.streamlit.services import get_drive_db
from apps.streamlit.tabs import (
    asset_classes,
    collection,
    introduction,
    paper_trading,
    reports,
    stocks,
)
from invest_assistant import config

st.set_page_config(page_title="추세추종 투자 어시스턴트", layout="wide")

views = [
    ("소개", introduction.render),
    ("대표 자산군 분석", asset_classes.render),
    ("종목 차트 (S&P 500)", stocks.render),
]
if config.STREAMLIT_PUBLIC_MODE:
    try:
        snapshot = get_drive_db()
        snapshot.validate()
        st.caption(f"공개 조회 · 데이터 업데이트: {snapshot.generated_at()} · 실시간 시세가 아닙니다.")
    except (ValueError, RuntimeError, OSError):
        st.error("공개 데이터를 준비 중입니다. 잠시 후 다시 접속해주세요.")
        st.stop()
else:
    views.append(("데이터 적재", collection.render))
views.append(("리포트 히스토리", reports.render))
if not config.STREAMLIT_PUBLIC_MODE:
    views.append(("모의 투자", paper_trading.render))

for tab, (_, render) in zip(st.tabs([label for label, _ in views]), views):
    with tab:
        render()

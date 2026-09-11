from __future__ import annotations

import logging

import streamlit as st

from apps.streamlit.components.log_viewer import _StreamlitLogHandler
from apps.streamlit.services import get_universe, load_ticker_data
from invest_assistant import universe as instrument_universe
from invest_assistant.pipelines import collect as collection_pipeline
from invest_assistant.storage.drive import DriveDB


def render():
    st.header("전체 데이터 적재")
    st.write(
        "S&P 500 종목 유니버스를 최신 상태로 동기화(편입/편출 반영)하고, "
        "전 종목 및 대표 자산군 ETF(SPY/GLD/TLT/DBC)의 최신 시세를 Google Drive에 적재합니다."
    )

    if st.button("전체 데이터 적재", type="primary"):
        log_placeholder = st.empty()
        handler = _StreamlitLogHandler(log_placeholder)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))

        root_logger = logging.getLogger()
        previous_level = root_logger.level
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        try:
            with st.spinner("진행 중... (500여 종목 처리라 수 분~수십 분 걸릴 수 있습니다)"):
                db = DriveDB()
                sync_result = collection_pipeline.run_full_collection(db)
            handler._flush()
            st.success(
                f"완료! 활성 종목 {len(sync_result['active'])}개 "
                f"(신규 편입 {len(sync_result['added'])}개, 편출 {len(sync_result['inactive'])}개) "
                f"+ 자산군 ETF {len(instrument_universe.ASSET_CLASS_TICKERS)}개"
            )
            get_universe.clear()
            load_ticker_data.clear()
        except Exception as e:
            handler._flush()
            st.error(f"오류 발생: {e}")
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(previous_level)

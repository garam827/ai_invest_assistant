from __future__ import annotations

import pandas as pd
import streamlit as st

from apps.streamlit.services import (
    get_report_dates,
    get_report_html,
    get_signal_history,
    get_test_report_dates,
)
from invest_assistant import config
from invest_assistant import universe as instrument_universe


def render():
    st.header("일일 리포트 히스토리")

    report_dates = get_report_dates()
    signal_history = get_signal_history()
    if not report_dates and not signal_history:
        st.info("아직 저장된 리포트가 없습니다. 크론(recommend.yml)이 최소 한 번 실행된 뒤 표시됩니다.")
    else:
        report_tickers = list(instrument_universe.ASSET_CLASS_TICKERS)
        ACTION_SHORT = {"매수": "B", "HOLD": "H", "매도": "S"}
        ACTION_CELL_STYLE = {"B": "color: green", "H": "color: gray", "S": "color: red"}

        # 표는 리포트가 발행된 날짜뿐 아니라 _signal_history.json에 있는 모든 날짜(가격 기반
        # 백필 포함, [기능 5] 참고 — 최대 5년치)를 다 보여준다. 리포트가 없는 날짜는 "링크"
        # 칸만 비워두고(None) 액션 컬럼은 그대로 채운다 — v3.35, 리포트 히스토리 표를
        # "발행된 리포트 목록"에서 "시그널 이력 전체 + 리포트 유무" 표로 확장.
        report_date_set = set(report_dates)
        all_dates = sorted(set(signal_history) | report_date_set, reverse=True)

        history_rows = []
        for date in all_dates:
            day_actions = signal_history.get(date, {})
            row = {"날짜": date}
            for ticker in report_tickers:
                row[ticker] = ACTION_SHORT.get(day_actions.get(ticker), "-")
            row["링크"] = f"{config.REPORT_BASE_URL}/{date}.html" if date in report_date_set else None
            history_rows.append(row)

        history_df = pd.DataFrame(history_rows)
        styled_history_df = history_df.style.map(
            lambda v: ACTION_CELL_STYLE.get(v, ""), subset=report_tickers
        )
        st.dataframe(
            styled_history_df,
            hide_index=True,
            width="stretch",
            column_config={"링크": st.column_config.LinkColumn("링크", display_text=r"([^/]+)$")},
        )
        st.caption("B=매수 · H=HOLD · S=매도")
        st.download_button(
            "전체 시그널 이력 CSV 다운로드",
            # utf-8-sig: BOM을 붙여야 엑셀에서 한글이 안 깨지고 정상적으로 열린다.
            data=history_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="signal_history.csv",
            mime="text/csv",
            key="signal_history_csv_download",
        )

        # 테스트/샘플 발행("_test" 접미어)은 GitHub Pages에 전혀 게시되지 않아(v3.27) 위
        # 표/링크에는 안 나온다 — 이 토글을 켜면 다운로드 목록에만 포함시켜, Drive에 저장된
        # 테스트 리포트 내용을 직접 받아서 확인할 수 있게 한다(기본은 꺼짐).
        include_test_reports = st.toggle("테스트/샘플 리포트도 다운로드 목록에 포함", key="include_test_reports")
        download_choices = {d: d for d in report_dates}
        if include_test_reports:
            for test_date in get_test_report_dates():
                download_choices[f"{test_date.removesuffix('_test')} (테스트)"] = test_date

        with st.form("report_download_form"):
            dl_cols = st.columns([3, 1])
            download_label = dl_cols[0].selectbox(
                "다운로드할 날짜", list(download_choices), key="report_download_date", label_visibility="collapsed"
            )
            download_submitted = dl_cols[1].form_submit_button("준비", width="stretch")

        if download_submitted:
            download_date = download_choices[download_label]
            report_html = get_report_html(download_date)
            if report_html is None:
                st.warning(f"{download_date} 리포트를 불러오지 못했습니다.")
            else:
                st.download_button(
                    f"{download_date}.html 다운로드",
                    data=report_html,
                    file_name=f"{download_date}.html",
                    mime="text/html",
                    key="report_download_button",
                )

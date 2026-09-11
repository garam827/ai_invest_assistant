from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from apps.streamlit.constants import ALL_SECTORS_LABEL
from apps.streamlit.services import get_drive_db, get_paper_positions, get_universe
from invest_assistant import universe as instrument_universe
from invest_assistant.portfolio import paper as paper_trading


def render():
    st.header("모의 투자 (Paper Trading)")
    st.caption("특정 종목을 특정일 종가에 매수했다고 가정하고, 그 포지션의 손익을 자동으로 추적합니다.")

    st.subheader("새 포지션 추가")
    paper_ticker_group = st.radio(
        "종목 유형", ["대표 자산군", "S&P 500 개별종목"], key="paper_ticker_group", horizontal=True
    )

    if paper_ticker_group == "대표 자산군":
        paper_categories = sorted({info["category"] for info in instrument_universe.ASSET_CLASS_TICKERS.values()})
        paper_category = st.selectbox("자산군 카테고리", paper_categories, key="paper_category_select")
        paper_candidates = [
            (ticker, info["label"])
            for ticker, info in instrument_universe.ASSET_CLASS_TICKERS.items()
            if info["category"] == paper_category
        ]
    else:
        paper_universe = get_universe()
        paper_sector_map = paper_universe["sectors"]
        paper_sector_options = (
            [ALL_SECTORS_LABEL] + sorted(set(paper_sector_map.values())) if paper_sector_map else [ALL_SECTORS_LABEL]
        )
        paper_sector = st.selectbox("섹터/테마", paper_sector_options, key="paper_sector_select")
        paper_filtered_tickers = (
            paper_universe["tickers"]
            if paper_sector == ALL_SECTORS_LABEL
            else [t for t in paper_universe["tickers"] if paper_sector_map.get(t) == paper_sector]
        )
        paper_candidates = [(t, t) for t in paper_filtered_tickers]

    paper_label_to_ticker = {label: ticker for ticker, label in paper_candidates}
    if not paper_label_to_ticker:
        st.warning("선택 가능한 종목이 없습니다.")
    else:
        paper_label = st.selectbox(
            f"종목 선택 ({len(paper_label_to_ticker)}개)", list(paper_label_to_ticker), key="paper_ticker_select"
        )
        paper_ticker = paper_label_to_ticker[paper_label]
        paper_entry_date = st.date_input("매수일", value=datetime.date.today(), key="paper_entry_date")

        suggested_price = paper_trading.preview_price(get_drive_db(), paper_ticker, str(paper_entry_date))
        if suggested_price is not None:
            st.info(f"제안 체결가 ({paper_entry_date} 기준 종가): {suggested_price:.2f}")
        else:
            st.warning(f"{paper_ticker}의 {paper_entry_date} 이전 시세 데이터가 없습니다. '데이터 적재' 탭에서 먼저 수집해주세요.")

        with st.form("paper_open_form"):
            col1, col2 = st.columns(2)
            with col1:
                paper_price_input = st.number_input(
                    "체결가", value=float(suggested_price) if suggested_price is not None else 0.0, min_value=0.0, step=0.01
                )
            with col2:
                paper_qty_input = st.number_input("수량", min_value=1, step=1, value=1)
            paper_open_submitted = st.form_submit_button("포지션 추가", type="primary")

        if paper_open_submitted:
            if paper_price_input <= 0:
                st.error("체결가를 확인할 수 없어 포지션을 추가하지 못했습니다.")
            else:
                paper_trading.open_position(
                    get_drive_db(), paper_ticker, str(paper_entry_date), paper_qty_input, entry_price=paper_price_input
                )
                get_paper_positions.clear()
                st.success(f"{paper_ticker} {paper_qty_input}주 매수 포지션을 추가했습니다.")
                st.rerun()

    st.divider()
    st.subheader("보유 중인 포지션")
    paper_all_positions = get_paper_positions()
    paper_open_positions = [p for p in paper_all_positions if p["status"] == "open"]
    paper_closed_positions = [p for p in paper_all_positions if p["status"] == "closed"]

    if not paper_open_positions:
        st.info("보유 중인 모의 투자 포지션이 없습니다.")
    else:
        for position in paper_open_positions:
            with st.container(border=True):
                cols = st.columns([1.3, 1, 1, 0.8, 1, 1.3, 1])
                cols[0].markdown(f"**{position['ticker']}**")
                cols[1].caption(f"매수일: {position['entry_date']}")
                cols[2].caption(f"매수가: {position['entry_price']:.2f}")
                cols[3].caption(f"수량: {position['quantity']}")
                if position["current_price"] is not None:
                    cols[4].caption(f"현재가: {position['current_price']:.2f}")
                    pnl_color = "green" if position["unrealized_pnl"] >= 0 else "red"
                    cols[5].markdown(
                        f":{pnl_color}[{position['unrealized_pnl']:+.2f} ({position['unrealized_pnl_pct']:+.2f}%)]"
                    )
                else:
                    cols[4].caption("현재가: N/A")
                    cols[5].caption("손익: N/A")
                # created_at은 ISO 타임스탬프(예: "2026-07-23T09:12:00+00:00") — 이 포지션을
                # "언제 설정했는지"(entry_date와 별개로, 과거 날짜로 소급 입력했을 수 있음)를 보여준다.
                cols[6].caption(f"설정일: {position['created_at'][:10]}")

                with st.form(f"close_form_{position['id']}"):
                    close_cols = st.columns([1, 1, 1])
                    with close_cols[0]:
                        exit_date_input = st.date_input(
                            "청산일", value=datetime.date.today(), key=f"exit_date_{position['id']}"
                        )
                    with close_cols[1]:
                        default_exit_price = (
                            position["current_price"] if position["current_price"] is not None else position["entry_price"]
                        )
                        exit_price_input = st.number_input(
                            "청산가",
                            value=float(default_exit_price),
                            min_value=0.0,
                            step=0.01,
                            key=f"exit_price_{position['id']}",
                        )
                    with close_cols[2]:
                        st.write("")
                        close_submitted = st.form_submit_button("청산", width="stretch")

                if close_submitted:
                    paper_trading.close_position(
                        get_drive_db(), position["id"], exit_date=str(exit_date_input), exit_price=exit_price_input
                    )
                    get_paper_positions.clear()
                    st.success(f"{position['ticker']} 포지션을 청산했습니다.")
                    st.rerun()

    with st.expander(f"청산 내역 ({len(paper_closed_positions)}건)"):
        if not paper_closed_positions:
            st.caption("청산된 포지션이 없습니다.")
        else:
            closed_df = pd.DataFrame(
                [
                    {
                        "티커": p["ticker"],
                        "매수일": p["entry_date"],
                        "매수가": p["entry_price"],
                        "청산일": p["exit_date"],
                        "청산가": p["exit_price"],
                        "수량": p["quantity"],
                        "설정일": p["created_at"][:10],
                        "실현손익": p["realized_pnl"],
                        "실현손익%": p["realized_pnl_pct"],
                    }
                    for p in paper_closed_positions
                ]
            )
            st.dataframe(closed_df, width="stretch", hide_index=True)

from __future__ import annotations

import pandas as pd
import streamlit as st

from apps.streamlit.constants import PERIOD_OPTIONS
from apps.streamlit.services import get_recommendation, load_ticker_data
from invest_assistant import config
from invest_assistant.analysis import signals as signal_engine
from invest_assistant.reporting import charts as chart_builder


def render_ticker_chart(ticker: str, period_label: str, subtitle: str, key_prefix: str) -> None:
    """Shared chart+metrics+LLM-recommendation renderer, used by both the asset-class and S&P tabs."""
    raw_df = load_ticker_data(ticker)
    if raw_df is None or raw_df.empty:
        st.warning(f"{ticker} 데이터가 없습니다. '데이터 적재' 탭에서 먼저 수집해주세요.")
        return

    # Donchian(100일)/ATR은 룩백이 필요하므로 전체 히스토리로 지표를 계산한 뒤, 화면 표시 구간만 잘라낸다.
    signals = signal_engine.compute_signals(raw_df)
    view = chart_builder.slice_to_period(signals, PERIOD_OPTIONS[period_label])

    latest = signals.iloc[-1]
    prev_close = signals.iloc[-2]["Close"] if len(signals) > 1 else latest["Close"]
    change = latest["Close"] - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0

    today_signal = "매수 돌파" if (latest["Breakout_20"] or latest["Breakout_100"]) else "-"
    if latest["Volume_Surge"] and today_signal == "-":
        today_signal = "거래량 급증"

    header_col, m1, m2, m3, m4 = st.columns([2, 1, 1, 1, 1])
    header_col.markdown(f"## {ticker}")
    if subtitle:
        header_col.caption(subtitle)
    m1.metric("현재가", f"{latest['Close']:.2f}", delta=f"{change:+.2f} ({change_pct:+.2f}%)")
    m2.metric("ATR (14일)", f"{latest['ATR']:.2f}" if pd.notna(latest["ATR"]) else "N/A")
    m3.metric("트레일링 스탑", f"{latest['Trailing_Stop']:.2f}" if pd.notna(latest["Trailing_Stop"]) else "N/A")
    m4.metric("오늘 시그널", today_signal)

    fig = chart_builder.build_ticker_chart_figure(ticker, view)

    with st.container(border=True):
        st.plotly_chart(fig, width="stretch", key=f"{key_prefix}_chart")

    st.subheader("Mr. Serenity의 매매 추천")
    try:
        # 차트(추세) 렌더링과 뉴스/LLM 분석 호출을 항상 분리 — "조회"는 차트만 그리고,
        # 이 버튼을 눌러야만 Exa/LLM을 호출한다(배포 모드와 무관하게 동일하게 적용,
        # 이전에는 config.STREAMLIT_ENABLE_LLM=false일 때만 분리되어 있었음). 티커별
        # st.session_state 키로 게이팅해 종목을 바꾸면 자동으로 다시 잠긴다.
        trigger_key = f"{key_prefix}_news_triggered_{ticker}"
        if not st.session_state.get(trigger_key):
            note = "뉴스 수집·분석은 외부 API를 호출하므로 버튼을 눌러야 실행됩니다."
            if not config.STREAMLIT_ENABLE_LLM:
                note += " (LLM 서술 분석은 이 배포본에서 비활성화되어 있으며, 규칙 기반 설명으로 대체됩니다.)"
            st.info(note)
            if not st.button("뉴스/분석 불러오기", key=f"{key_prefix}_load_btn_{ticker}"):
                return
            st.session_state[trigger_key] = True

        reco = get_recommendation(ticker, str(latest["Date"]), config.STREAMLIT_ENABLE_LLM)
        if reco is None:
            st.info("데이터가 오래되어(신선도 기준 초과) 추천을 생성하지 않았습니다. '데이터 적재' 탭에서 갱신해주세요.")
            return
        action_color = {"매수": "green", "HOLD": "gray", "매도": "red"}.get(reco["action"], "gray")
        st.markdown(f"#### :{action_color}[추천: {reco['action']}]")
        st.write(reco["text"])

        news_items = reco.get("news", [])
        if news_items:
            st.markdown("###### 분석에 사용된 뉴스")
            for item in news_items:
                with st.container(border=True):
                    title = item.get("title", "")
                    link = item.get("link", "")
                    st.markdown(f"**[{title}]({link})**" if link else f"**{title}**")
                    meta = " · ".join(filter(None, [item.get("publisher", ""), item.get("published_at", "")]))
                    if meta:
                        st.caption(meta)
                    if item.get("summary"):
                        st.write(item["summary"])
    except Exception as e:
        st.error(f"LLM 분석 실패: {e}")

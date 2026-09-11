from __future__ import annotations

import streamlit as st

from apps.streamlit.constants import INDICATOR_TABLE


def render():
    st.header("톰 바소 스타일 추세추종 투자 어시스턴트")

    with st.expander("이 프로그램에 대하여 — 톰 바소(Tom Basso)의 투자 철학", expanded=True):
        st.markdown(
            """
이 앱은 전설적인 시스템 트레이더 **톰 바소(Tom Basso)** — 별명 "미스터 세레니티(Mr. Serenity)" — 의 투자 철학을 규칙 기반 소프트웨어로 구현한 추세추종(Trend Following) 투자 어시스턴트입니다.

**톰 바소의 핵심 철학**
- **감정을 배제한 기계적 시스템**: 시장이 어디로 갈지 예측하지 않는다. 가격이 실제로 움직인 뒤, 정해진 규칙대로만 반응한다.
- **추세는 친구다**: 상승 추세가 확인되면(Donchian 채널 상단 돌파) 올라타고, 추세가 꺾이면(트레일링 스탑 이탈) 미련 없이 나온다.
- **손실은 짧게, 수익은 길게**: ATR 기반 변동성 손절로 한 번의 손실이 자산에 미치는 영향을 제한하고(리스크 기본 1%), 추세가 지속되는 동안은 트레일링 스탑만 따라 올리며 수익을 최대한 태운다.
- **평온함(Serenity)**: 뉴스의 공포와 탐욕에 휘둘리지 않는다. 이 앱의 LLM은 뉴스를 "규칙적 시그널을 뒷받침하는 팩트"와 "무시해도 되는 소음"으로만 걸러내도록 설계되어 있다.

**이 프로그램의 목표**
1. S&P 500 개별 종목 + 대표 자산군(S&P 500 지수·비트코인·금·미국 국채·원자재)에 동일한 규칙 기반 시스템을 자동 적용
2. 매일 시세를 수집·축적하고 Donchian/ATR/트레일링 스탑을 자동 계산
3. 시그널 관련 뉴스를 수집해 LLM이 노이즈를 걸러내고, 규칙에 따른 매수/HOLD/매도를 추천
4. 사람의 감정이 아니라 시스템이 판단하게 함으로써 일관되고 반복 가능한 투자 의사결정을 돕는다

실제 분석은 **"대표 자산군 분석"**, **"종목 차트 (S&P 500)"** 탭에서 진행합니다.
"""
        )

    with st.expander("사용된 지표 설명", expanded=True):
        # st.table은 컬럼 폭을 직접 제어할 수 없어 "지표" 이름 칸이 내용 길이에 따라 과하게
        # 넓어지고 "설명" 칸이 좁아져 줄바꿈이 자주/어색하게 일어났다 — 직접 HTML 표를 그려
        # 지표:설명 폭 비율을 고정하고, 한글이 음절 중간에서 잘리지 않도록 word-break을 지정.
        indicator_rows_html = "".join(
            f"<tr><td>{name}</td><td>{desc}</td></tr>"
            for name, desc in zip(INDICATOR_TABLE.index, INDICATOR_TABLE["설명"])
        )
        st.markdown(
            f"""
            <style>
            .indicator-table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
            .indicator-table col.name {{ width: 26%; }}
            .indicator-table col.desc {{ width: 74%; }}
            .indicator-table th, .indicator-table td {{
                border: 1px solid rgba(128, 128, 128, 0.3);
                padding: 0.5rem 0.8rem;
                text-align: left;
                vertical-align: top;
                word-break: keep-all;
                overflow-wrap: break-word;
                line-height: 1.5;
            }}
            .indicator-table th {{ font-weight: 600; }}
            </style>
            <table class="indicator-table">
              <colgroup><col class="name"><col class="desc"></colgroup>
              <thead><tr><th>지표</th><th>설명</th></tr></thead>
              <tbody>{indicator_rows_html}</tbody>
            </table>
            """,
            unsafe_allow_html=True,
        )

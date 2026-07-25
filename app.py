"""Streamlit entry point (single page, tab-separated): [기능 4].

Tab 1 — 소개: 이 프로그램의 목표, 톰 바소 철학, 사용된 지표 설명. 분석 기능은 없다.
Tab 2 — 대표 자산군 분석: 톰 바소 추세추종 시스템을 data_fetcher.ASSET_CLASS_TICKERS(주식/암호화폐/
귀금속/채권/원자재/통화 카테고리, ETF 또는 현물 프록시)에 적용.
Tab 3 — 종목 차트 (S&P 500): 개별 종목 차트.
Tab 4 — 데이터 적재: S&P 500 유니버스 동기화 + 전 종목/자산군 시세 갱신을 한 번에 실행.
Tab 5 — 리포트 히스토리: 크론이 report_builder로 만들어 Drive에 저장한 날짜별 일일 리포트(전 종목
차트 + LLM 종합 해설)를 그대로 다시 렌더링.
Tab 6 — 모의 투자: 사용자가 직접 기록하는 가상의 매수/매도 포지션과 그 손익을 추적 (paper_trading.py,
paper_trading_spec.md 참고). 크론이 아니라 이 UI에서만 포지션을 열고 닫는다.

두 차트 탭(2, 3) 모두 같은 render_ticker_chart를 공유한다: 캔들+지표 오버레이,
과거 매수/청산 시그널 발생일 마커, 그리고 뉴스+시그널 상태 기반 LLM 매매 추천.
"""
from __future__ import annotations

import datetime
import logging

import pandas as pd
import streamlit as st

import chart_builder
import config
import data_fetcher
import paper_trading
import recommendation_engine
import report_builder
import signal_engine
from drive_db import DriveDB

st.set_page_config(page_title="추세추종 투자 어시스턴트", layout="wide")

PERIOD_OPTIONS = {
    "1개월": 30,
    "3개월": 90,
    "6개월": 180,
    "1년": 365,
    "2년": 730,
    "전체": None,
}
DEFAULT_PERIOD_LABEL = "6개월"
ALL_SECTORS_LABEL = "전체"

INDICATOR_TABLE = pd.DataFrame(
    [
        {
            "지표": "볼린저 밴드 (20일 SMA ± 2표준편차)",
            "설명": "최근 20일 종가의 변동성(표준편차) 기반 밴드. 상단 근접=단기 과매수, 하단 근접=단기 과매도로 흔히 해석되고, 밴드 폭 축소(스퀴즈)는 변동성 확대·돌파 임박 신호로도 봅니다. 톰 바소 매매 규칙(Donchian/ATR)에 직접 쓰이진 않는 보조 참고 지표.",
        },
        {
            "지표": "Donchian Channel (20일/100일)",
            "설명": "최근 N일간 고가·저가로 만든 밴드. 종가가 20일 상단선을 상향 돌파하면 매수 시그널, 100일 상단선은 더 장기적인 추세 확인용 보조 지표.",
        },
        {
            "지표": "ATR (Average True Range, 14일, Wilder's smoothing)",
            "설명": "최근 변동성 크기. 값이 클수록 하루 변동폭이 크다는 뜻이며, 손절폭·포지션 사이징 계산의 기준.",
        },
        {
            "지표": "트레일링 스탑 = 최근 20일 최고가 − 3 × ATR",
            "설명": "추세를 따라 함께 올라가는 손절선. 종가가 이 선 아래로 내려오면 청산(매도) 시그널.",
        },
        {
            "지표": "거래량 급증 (Volume Surge)",
            "설명": "당일 거래량이 최근 20일 평균 거래량의 1.5배 이상이면 거래량 차트에서 강조 표시. 매수/매도 판정 자체에는 관여하지 않음(거래량이 낮아도 가격이 돌파하면 그대로 매수 판정) — 돌파 신뢰도를 가늠하는 참고 지표이자, 여러 종목을 우선순위로 스캔하는 기능(`scan_for_signals`, 아직 UI 미연결)에서 순위를 매기는 용도로만 쓰인다.",
        },
        {
            "지표": "매수/청산 시그널 마커 (▲ / ▼)",
            "설명": "초록 세모(▲)는 Donchian 상단 돌파가 처음 발생한 날(매수 트리거), 빨간 세모(▼)는 트레일링 스탑 하향 이탈이 처음 발생한 날(청산 트리거). 추세가 지속되는 동안 매일 반복 표시하지 않고, 신호가 새로 발생한 날만 표시.",
        },
        {
            "지표": "일목균형표 구름 (Ichimoku 선행스팬A·B)",
            "설명": "선행스팬A·B로 이루어진 구름(26일 선행 투영)만 차트에 표시 — 양운(선행스팬A≥B, 상승 추세, 연한 붉은색)/음운(하락 추세, 연한 파란색)으로 구분. 매수/매도 추천 코멘트에 '구름 대비 가격 위치'가 시그널과 일치하는지 참고용으로만 반영되며, 톰 바소 매매 규칙(Donchian/ATR)에 직접 쓰이진 않는 보조 참고 지표.",
        },
    ]
).set_index("지표")


@st.cache_resource
def get_drive_db() -> DriveDB:
    return DriveDB()


@st.cache_data(ttl=3600, show_spinner="Drive에서 종목 목록 불러오는 중...")
def get_universe() -> dict:
    db = get_drive_db()
    universe = db.load_json(data_fetcher.UNIVERSE_FILENAME)
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
    return report_builder.list_report_dates(get_drive_db())


@st.cache_data(ttl=300, show_spinner="테스트 리포트 목록 불러오는 중...")
def get_test_report_dates() -> list[str]:
    """Short TTL — unlike real reports (one per day), test dates can be created/re-run
    within the same session while someone is actively testing the pipeline."""
    return report_builder.list_test_report_dates(get_drive_db())


@st.cache_data(ttl=86400, show_spinner="리포트 불러오는 중...")
def get_report_html(date: str) -> str | None:
    """Cached by date, not TTL alone — a past date's report never changes once published."""
    return report_builder.load_report(get_drive_db(), date)


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


class _StreamlitLogHandler(logging.Handler):
    """Streams log records into a Streamlit code block, throttled to avoid excessive redraws."""

    def __init__(self, placeholder, flush_every: int = 5):
        super().__init__()
        self.placeholder = placeholder
        self.flush_every = flush_every
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))
        if len(self.lines) % self.flush_every == 0:
            self._flush()

    def _flush(self) -> None:
        self.placeholder.code("\n".join(self.lines[-300:]))


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
        if not config.STREAMLIT_ENABLE_LLM:
            # Public-deployment mode: news/analysis costs API quota per click, so require an
            # explicit trigger instead of auto-firing on every "조회" — keyed by ticker so
            # switching tickers naturally resets it without any manual state cleanup.
            trigger_key = f"{key_prefix}_news_triggered_{ticker}"
            if not st.session_state.get(trigger_key):
                st.info("API 사용량 관리를 위해 뉴스 수집·분석은 버튼을 눌러야 실행됩니다. (LLM 서술 분석은 이 배포본에서 비활성화되어 있으며, 규칙 기반 설명으로 대체됩니다.)")
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


tab_intro, tab_asset, tab_sp500, tab_collect, tab_report, tab_paper = st.tabs(
    ["소개", "대표 자산군 분석", "종목 차트 (S&P 500)", "데이터 적재", "리포트 히스토리", "모의 투자"]
)

# ---------------------------------------------------------------------------
# 탭 1: 소개 — 분석 기능 없이 프로그램 목표/철학/지표 설명만. 실제 지표 분석은 탭 2부터.
# ---------------------------------------------------------------------------
with tab_intro:
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

# ---------------------------------------------------------------------------
# 탭 2: 대표 자산군 분석 — S&P 500 자체(및 비트코인/금/미국채/원자재)도 동일한 추세추종 규칙을
# ETF(또는 현물) 프록시로 적용할 수 있다. 원지수(^GSPC 등)는 직접 거래할 수 없고 거래량
# 데이터도 부실하므로, 유동성이 높은 프록시로 대신 추적한다.
# ---------------------------------------------------------------------------
with tab_asset:
    st.header("대표 자산군별 추세추종 분석")
    st.caption("S&P 500·비트코인·금·미국 국채·원자재(원유/천연가스/농산물/구리 등)를 유동성 높은 ETF(또는 현물)로 대신 추적해 동일한 Donchian/ATR 규칙을 적용합니다.")

    if "selected_asset_ticker" not in st.session_state:
        st.session_state.selected_asset_ticker = None
        st.session_state.selected_asset_period = DEFAULT_PERIOD_LABEL

    # 카테고리 선택은 폼 밖에 둬서 클릭 즉시 세부 종목 드롭다운을 좁혀준다 (탭2의 섹터 필터와 동일 패턴).
    asset_categories = sorted({info["category"] for info in data_fetcher.ASSET_CLASS_TICKERS.values()})
    asset_category = st.selectbox("자산군 카테고리", asset_categories, key="asset_category_select")
    filtered_assets = [
        (ticker, info["label"]) for ticker, info in data_fetcher.ASSET_CLASS_TICKERS.items() if info["category"] == asset_category
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
        asset_info = data_fetcher.ASSET_CLASS_TICKERS[active_asset_ticker]
        render_ticker_chart(
            active_asset_ticker,
            st.session_state.selected_asset_period,
            subtitle=f"{asset_info['label']} — {asset_info['description']}",
            key_prefix="asset",
        )

# ---------------------------------------------------------------------------
# 탭 2: 종목 차트 (S&P 500) — 개별 종목 분석
# ---------------------------------------------------------------------------
with tab_sp500:
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

# ---------------------------------------------------------------------------
# 탭 3: 데이터 적재
# ---------------------------------------------------------------------------
with tab_collect:
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
                sync_result = data_fetcher.run_full_collection(db)
            handler._flush()
            st.success(
                f"완료! 활성 종목 {len(sync_result['active'])}개 "
                f"(신규 편입 {len(sync_result['added'])}개, 편출 {len(sync_result['inactive'])}개) "
                f"+ 자산군 ETF {len(data_fetcher.ASSET_CLASS_TICKERS)}개"
            )
            get_universe.clear()
            load_ticker_data.clear()
        except Exception as e:
            handler._flush()
            st.error(f"오류 발생: {e}")
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(previous_level)

# ---------------------------------------------------------------------------
# 탭 4: 리포트 히스토리 — 크론(recommend.yml)이 report_builder로 만들어 Drive에 저장한
# 날짜별 일일 리포트 이력을 하나의 st.dataframe으로 보여준다(v3.29, st.container 카드
# 나열에서 교체 — 전체 데이터셋이 이미 메모리에 있으니 표 위젯 하나로 정렬/스크롤까지
# 기본 지원받는 게 더 간단하다). 링크 컬럼은 st.column_config.LinkColumn으로 GitHub
# Pages URL을 클릭 가능한 링크로 렌더링(파일명만 표시). 액션은 날짜별
# _recommendations_{date}.json을 하나씩 읽는 대신, recommendation_engine이 매일 실제(비-테스트)
# 발행 때마다 갱신해 두는 가벼운 누적 파일 _signal_history.json을 통째로 한 번만 읽어서 채운다
# (v3.28). 리포트 본문 자체는 GitHub Pages 링크로 새 탭에서 열어 원래 설계된 전체 폭/단일
# 스크롤로 보게 한다(v3.24) — iframe에 그대로 욱여넣으면 리포트가 v3.4에서 의도적으로 없앤
# max-width 제한 없는 넓은 레이아웃을 Streamlit의 좁은 컨테이너 폭으로 다시 눌러버리고,
# 바깥 페이지 스크롤과 iframe 내부 스크롤이 겹쳐 가독성이 나빠졌다. "다운로드"는
# st.download_button이 데이터프레임 셀 안에 들어갈 수 없어(지원되는 컬럼 타입이 아님)
# 표 아래 별도의 작은 st.form(날짜 선택 + 준비 버튼 한 줄)으로 분리했다(v3.29) — Drive에는
# 저장됐지만 GitHub Pages에는 아직 없는 경우의 폴백. 수동/샘플 테스트 발행("_test" 접미어)은
# report_builder.list_report_dates에서 이미 걸러져 목록에 안 나온다(v3.25).
# ---------------------------------------------------------------------------
with tab_report:
    st.header("일일 리포트 히스토리")

    report_dates = get_report_dates()
    signal_history = get_signal_history()
    if not report_dates and not signal_history:
        st.info("아직 저장된 리포트가 없습니다. 크론(recommend.yml)이 최소 한 번 실행된 뒤 표시됩니다.")
    else:
        report_tickers = list(data_fetcher.ASSET_CLASS_TICKERS)
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

# ---------------------------------------------------------------------------
# 탭 5: 모의 투자 — 사용자가 직접 기록하는 가상의 매수 포지션과 그 손익 추적.
# 크론이 아니라 이 UI에서만 포지션을 열고 닫는다 (paper_trading_spec.md 참고).
# ---------------------------------------------------------------------------
with tab_paper:
    st.header("모의 투자 (Paper Trading)")
    st.caption("특정 종목을 특정일 종가에 매수했다고 가정하고, 그 포지션의 손익을 자동으로 추적합니다.")

    st.subheader("새 포지션 추가")
    paper_ticker_group = st.radio(
        "종목 유형", ["대표 자산군", "S&P 500 개별종목"], key="paper_ticker_group", horizontal=True
    )

    if paper_ticker_group == "대표 자산군":
        paper_categories = sorted({info["category"] for info in data_fetcher.ASSET_CLASS_TICKERS.values()})
        paper_category = st.selectbox("자산군 카테고리", paper_categories, key="paper_category_select")
        paper_candidates = [
            (ticker, info["label"])
            for ticker, info in data_fetcher.ASSET_CLASS_TICKERS.items()
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

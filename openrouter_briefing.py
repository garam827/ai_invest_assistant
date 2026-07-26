"""'Mr. Serenity' LLM analysis via OpenRouter (default model: nvidia/nemotron-3-ultra-550b-a55b:free).

Two things this module does:
- generate_briefing: judges whether a signal ticker's news reinforces its long-term trend or is noise.
- generate_recommendation: given news + the current Donchian/ATR signal state, returns a mechanical
  buy/hold/sell call per Tom Basso's rules (used by the chart tabs' "조회" button).
"""
from __future__ import annotations

import re

import requests

import config

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "다음 수집된 [종목 뉴스]를 분석하여 시장의 단기적인 탐욕이나 공포(노이즈)를 철저히 배제하라. "
    "오직 이 뉴스가 장기 추세를 강화하는 팩트인지, 아니면 무시해도 되는 소음인지 "
    "평온하고 이성적인 시각으로 요약 브리핑을 작성하라."
)

RECOMMENDATION_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "너의 매매 원칙은 오직 규칙 기반의 기계적 추세추종이다: 종가가 Donchian 채널 상단을 상향 돌파하면 매수, "
    "종가가 트레일링 스탑(최근 고점 - 3×ATR) 아래로 내려오면 매도, 그 사이에는 보유(HOLD)다. "
    "뉴스의 감정이나 예측으로 판단하지 말고, 주어진 시그널 상태와 뉴스가 그 추세를 뒷받침하는 팩트인지만 "
    "걸러내어 위 규칙에 따라 최종 추천을 내려라. 답변 첫 줄은 반드시 '추천: 매수', '추천: HOLD', '추천: 매도' "
    "중 하나로 시작하고, 이어서 그 근거를 설명하라. "
    "시그널 상태에 일목균형표 구름 정보가 포함되어 있다면, 이는 어디까지나 보조 참고 정보다 — 이것만으로 "
    "위 추천(첫 줄)을 절대 바꾸지 마라. 다만 그 정보가 기계적 판정과 엇갈린다면(예: 매수인데 구름 아래/음운), "
    "비중을 줄여 진입하는 등 리스크 관리 코멘트를 근거 설명에 덧붙일 수 있다."
)

_RECOMMENDATION_PATTERN = re.compile(r"추천\s*[:：]\s*(매수|HOLD|매도)")

PORTFOLIO_OVERVIEW_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 오늘 대표 자산군들의 기계적 추세추종 판정 결과이고, 이어서 최근 며칠~30일간의 날짜별 "
    "자산군별 판정 이력이 함께 주어질 수 있다. 각 판정은 이미 규칙에 따라 확정된 사실이며, 너는 이 "
    "판정을 절대 바꾸거나 재해석하지 않는다. 다만 (1) 오늘 여러 자산군에 걸쳐 동시에 나타나는 추세와, "
    "(2) 최근 이력이 주어졌다면 그 안에서 관찰되는 추세 전환이나 동조화(예: 최근 며칠 사이 여러 자산군이 "
    "동시에 매수로 전환)를 감정 없이 담담한 사실 위주로 한 문단으로 종합 해설하라 — 향후 전망이나 예측은 "
    "절대 덧붙이지 마라."
)


def _format_news_for_prompt(ticker: str, news_items: list[dict]) -> str:
    if not news_items:
        return f"[{ticker}] 관련 금일 뉴스 없음."

    lines = [f"[{ticker}] 종목 뉴스:"]
    for item in news_items:
        lines.append(f"- {item['title']} ({item.get('publisher', '')}): {item.get('summary', '')}")
    return "\n".join(lines)


def _call_chat(system_prompt: str, user_prompt: str) -> str:
    if not config.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not set")

    response = requests.post(
        OPENROUTER_CHAT_URL,
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.OPENROUTER_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    if "choices" not in data:
        # Free-tier models occasionally return a 200 with no choices (rate limit, provider
        # hiccup, etc.) instead of a proper error status. Surface the actual reason instead
        # of letting a bare KeyError obscure it.
        error_message = (data.get("error") or {}).get("message", str(data)[:300])
        raise RuntimeError(f"OpenRouter response missing 'choices': {error_message}")

    return data["choices"][0]["message"]["content"].strip()


def generate_briefing(ticker: str, news_items: list[dict]) -> str:
    """Ask the configured OpenRouter model (as Mr. Serenity) whether today's news is trend-reinforcing or noise."""
    prompt = _format_news_for_prompt(ticker, news_items)
    if not news_items:
        prompt += " 뉴스가 없다는 사실 자체를 근거로 평온한 브리핑을 작성하라."
    return _call_chat(SYSTEM_PROMPT, prompt)


def generate_recommendation(
    ticker: str, news_items: list[dict], signal_summary: dict, ichimoku_confluence: dict | None = None
) -> dict:
    """Ask the LLM (as Mr. Serenity) for a mechanical 매수/HOLD/매도 call.

    `signal_summary` is the dict returned by signal_engine.get_latest_signal_summary.
    `ichimoku_confluence` (signal_engine.get_ichimoku_confluence) is advisory-only context —
    see RECOMMENDATION_SYSTEM_PROMPT, it must never change the parsed `action` below.
    Returns {"action": "매수"|"HOLD"|"매도", "text": full reasoning}. `action` defaults to
    "HOLD" if the model doesn't follow the required "추천: ..." prefix format.
    """
    news_block = _format_news_for_prompt(ticker, news_items)
    signal_block = (
        f"[현재 시그널 상태]\n"
        f"- 종가: {signal_summary['close']:.2f}\n"
        f"- ATR(14일): {signal_summary['atr']:.2f}\n"
        f"- 20일 상단 돌파 여부: {signal_summary['breakout_20']}\n"
        f"- 100일 상단 돌파 여부: {signal_summary['breakout_100']}\n"
        f"- 트레일링 스탑: {signal_summary['trailing_stop']:.2f}\n"
        f"- 청산 시그널(종가<트레일링스탑): {signal_summary['exit_signal']}\n"
        f"- 거래량 급증: {signal_summary['volume_surge']}"
    )
    if ichimoku_confluence is not None:
        position_kr = {"above": "구름 위", "below": "구름 아래", "inside": "구름 안"}[ichimoku_confluence["position"]]
        cloud_kr = "양운(상승 구름)" if ichimoku_confluence["cloud_bullish"] else "음운(하락 구름)"
        signal_block += f"\n- 일목균형표(보조 참고): {position_kr} · {cloud_kr}"
    prompt = f"{news_block}\n\n{signal_block}\n\n위 뉴스와 시그널 상태를 바탕으로 매수/HOLD/매도를 추천하라."

    text = _call_chat(RECOMMENDATION_SYSTEM_PROMPT, prompt)
    match = _RECOMMENDATION_PATTERN.search(text)
    action = match.group(1) if match else "HOLD"
    return {"action": action, "text": text}


def generate_portfolio_overview(results: dict, signal_history: dict | None = None) -> str:
    """One-paragraph cross-asset synthesis across the day's ASSET_CLASS_TICKERS results
    (report_builder.build_daily_report_html's LLM overview section). Commentary only —
    never changes any individual ticker's mechanical action.

    `signal_history` ({date: {ticker: action}}, optional, already windowed by the caller —
    see recommendation_engine._recent_signal_history) lets the synthesis also note trend
    shifts/synchronization across recent days, not just today's snapshot. Omitted if not given.
    """
    lines = ["[오늘의 자산군별 판정]"]
    for ticker, reco in results.items():
        lines.append(f"- {ticker}: {reco['action']} (종가 {reco['close']:.2f})")

    if signal_history:
        lines.append("\n[최근 시그널 이력 (날짜: 자산군=액션, ...)]")
        for date in sorted(signal_history, reverse=True):
            actions_str = ", ".join(f"{ticker}={action}" for ticker, action in signal_history[date].items())
            lines.append(f"- {date}: {actions_str}")

    prompt = "\n".join(lines) + "\n\n위 오늘의 판정과 최근 시그널 이력을 종합해 오늘 시장 상황을 한 문단으로 요약하라."
    return _call_chat(PORTFOLIO_OVERVIEW_SYSTEM_PROMPT, prompt)


PREDICTION_COMMENTARY_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 실험적 머신러닝 모델이 대표 자산군별로 추정한 '추세 점수'다 — "
    "log((향후 30일 예상 매수일수+1) / (향후 30일 예상 매도일수+1))로 계산되며, 이 모델은 "
    "과거 시그널 패턴만으로 학습됐고 검증이 제한적이다(단순 평균 예측 대비 소폭 개선 수준). "
    "각 자산의 예측값은 그 자산 자신의 과거 평균 점수와 함께 주어진다 — 점수가 음수인 것 "
    "자체는 매수(신고점 갱신, 하루짜리 이벤트)보다 매도(트레일링 스탑 하회, 여러 날 지속되는 "
    "상태) 신호가 구조적으로 훨씬 잦기 때문이며 이상 신호가 아니다. (1) 이번 예측이 그 자산의 "
    "과거 평균보다 높은지 낮은지, (2) 여러 자산군에 걸쳐 공통으로 나타나는 패턴을 감정 없이 "
    "담담한 사실 위주로 짚어라. 추가로 (3) 주식/암호화폐 같은 경기민감 자산군과 채권/통화 같은 "
    "안전자산군 사이에서 이 패턴이 상대적으로 어떻게 갈리는지를 근거로, 이것이 통상적인 경기 "
    "사이클(확장기/후기 확장기/수축기/회복기 등) 중 어떤 국면과 유사한 특징을 보이는지 참고 삼아 "
    "짧게 고찰해도 좋다 — 다만 이는 어디까지나 지금 나타난 자산군 간 상대적 패턴에 대한 참고적 "
    "해석일 뿐, 특정 자산의 향후 가격이나 방향성을 예측·전망하는 것이 아니며 확신에 찬 단정적 "
    "표현도 쓰지 마라. 이 해설은 이 실험적 모델의 결과를 설명하는 것일 뿐이며, 실제 매수/HOLD/매도 "
    "판정(기계적 규칙 기반)을 절대 바꾸거나 재해석하지 않는다."
)


def generate_prediction_commentary(predictions: dict) -> str:
    """One-paragraph synthesis of prediction_model's experimental trend-score simulation
    (report_builder.build_daily_report_html's "AI 예측 시뮬레이션" section — see
    prediction_model_spec.md). `predictions` is _prediction_simulation.json's own
    "predictions" dict ({ticker: {trend_score, historical_avg_score, ...}}).

    Commentary only — explicitly forbidden (see PREDICTION_COMMENTARY_SYSTEM_PROMPT) from
    predicting future price/direction or influencing any mechanical action, same
    advisory-only principle as generate_portfolio_overview/generate_recommendation. May
    also reflect on which economic-cycle phase the cross-asset pattern resembles (user
    request) -- scoped to a qualitative read of today's relative pattern, not a forecast.
    """
    lines = ["[자산군별 추세 점수 (실험적 ML 예측)]"]
    for ticker, pred in predictions.items():
        lines.append(f"- {ticker}: 예측 {pred['trend_score']:+.3f} (과거 평균 {pred['historical_avg_score']:+.3f})")
    prompt = (
        "\n".join(lines)
        + "\n\n위 자산군별 추세 점수를 각 자산의 과거 평균과 비교해 요약하고, "
        "이 패턴이 어떤 경기 사이클 국면과 유사한지도 참고 삼아 짚어 한 문단으로 정리하라."
    )
    return _call_chat(PREDICTION_COMMENTARY_SYSTEM_PROMPT, prompt)

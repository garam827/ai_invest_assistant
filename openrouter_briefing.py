"""'Mr. Serenity' LLM analysis via OpenRouter (default model: nvidia/nemotron-3-ultra-550b-a55b:free).

Two things this module does:
- generate_briefing: judges whether a signal ticker's news reinforces its long-term trend or is noise.
- generate_recommendation: given news + the current Donchian/ATR signal state, returns a mechanical
  buy/hold/sell call per Tom Basso's rules (used by the chart tabs' "조회" button).
"""
from __future__ import annotations

import logging
import re

import requests

import config

logger = logging.getLogger(__name__)

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
    "중 하나로 시작하고, 이어서 그 근거를 설명하라."
)

_RECOMMENDATION_PATTERN = re.compile(r"추천\s*[:：]\s*(매수|HOLD|매도)")


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


def generate_briefings(news_by_ticker: dict[str, list[dict]]) -> dict[str, str]:
    """Batch version: ticker -> briefing text, for every ticker that fired a signal today."""
    briefings: dict[str, str] = {}
    for ticker, news_items in news_by_ticker.items():
        try:
            briefings[ticker] = generate_briefing(ticker, news_items)
        except Exception:
            logger.exception("Failed to generate briefing for %s", ticker)
            briefings[ticker] = "브리핑 생성에 실패했습니다."
    return briefings


def generate_recommendation(ticker: str, news_items: list[dict], signal_summary: dict) -> dict:
    """Ask the LLM (as Mr. Serenity) for a mechanical 매수/HOLD/매도 call.

    `signal_summary` is the dict returned by signal_engine.get_latest_signal_summary.
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
    prompt = f"{news_block}\n\n{signal_block}\n\n위 뉴스와 시그널 상태를 바탕으로 매수/HOLD/매도를 추천하라."

    text = _call_chat(RECOMMENDATION_SYSTEM_PROMPT, prompt)
    match = _RECOMMENDATION_PATTERN.search(text)
    action = match.group(1) if match else "HOLD"
    return {"action": action, "text": text}

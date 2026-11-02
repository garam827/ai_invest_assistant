"""'Mr. Serenity' LLM analysis via an OpenAI-compatible chat API (default: OpenAI, see config.LLM_PROVIDER).

Two things this module does:
- generate_briefing: judges whether a signal ticker's news reinforces its long-term trend or is noise.
- generate_recommendation: given news + the current Donchian/ATR signal state, returns a mechanical
  buy/hold/sell call per Tom Basso's rules (used by the chart tabs' "조회" button).
"""
from __future__ import annotations

import re

import requests

from invest_assistant import config
from invest_assistant import universe as instrument_universe

CHAT_COMPLETIONS_PATH = "/chat/completions"

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
    "근거를 설명할 때 뉴스는 주제 키워드만 나열하지 말고, 수집된 기사 중 가장 관련성 높은 1~2건을 "
    "구체적으로 짚어 그 기사가 실제로 무슨 내용을 전하는지와 그것이 왜 지금의 추세(또는 청산 신호)를 "
    "뒷받침하는 팩트인지 혹은 무시해도 되는 노이즈인지를 풀어서 설명하라 — 기사 제목이나 발행처만 "
    "언급하고 넘어가지 마라. 뉴스가 없거나 기계적 판정과 무관하면 그 사실만 담백하게 언급하면 된다. "
    "시그널 상태에 일목균형표 구름 정보가 포함되어 있다면, 이는 어디까지나 보조 참고 정보다 — 이것만으로 "
    "위 추천(첫 줄)을 절대 바꾸지 마라. 다만 그 정보가 기계적 판정과 엇갈린다면(예: 매수인데 구름 아래/음운), "
    "비중을 줄여 진입하는 등 리스크 관리 코멘트를 근거 설명에 덧붙일 수 있다."
)

_RECOMMENDATION_PATTERN = re.compile(r"추천\s*[:：]\s*(매수|HOLD|매도)")

PORTFOLIO_OVERVIEW_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 오늘 대표 자산군들의 기계적 추세추종 판정 결과다(카테고리 표기 포함 — 주식/암호화폐는 "
    "위험자산, 채권/통화는 안전자산, 귀금속/원자재는 인플레이션·공급 충격에 대한 헤지 성격을 띤다). "
    "이어서 최근 며칠~30일간의 날짜별 자산군별 판정 이력이 함께 주어질 수 있다. 각 판정은 이미 규칙에 "
    "따라 확정된 사실이며, 너는 이 판정을 절대 바꾸거나 재해석하지 않는다.\n\n"
    "단, 판정을 티커별로 다시 나열하기만 하는 답변은 쓰지 마라 — 그 정보는 이미 표로 그대로 보인다. "
    "대신 다음을 종합해 '이 조합이 오늘 무엇을 의미하는지'를 설명하는 것이 이 해설의 목적이다: "
    "(1) 위험자산군과 안전자산군의 판정이 같은 방향으로 움직이는지 엇갈리는지, 그것이 시장의 위험 "
    "선호·회피 심리에 대해 무엇을 시사하는지, "
    "(2) 최근 이력이 주어졌다면 그 안에서 나타나는 추세 전환·동조화(예: 며칠 사이 여러 자산군이 동시에 "
    "매수로 전환)가 오늘 스냅샷 대비 상황을 강화하는 흐름인지 되돌리는 흐름인지, "
    "(3) 특정 자산군만 유독 다른 자산군과 다르게 움직였다면 그 괴리가 왜 주목할 만한지. "
    "이 해석은 어디까지나 오늘 나타난 자산군 간 상대적 패턴에 대한 참고적 해설일 뿐, 특정 자산의 향후 "
    "가격이나 방향성을 예측·전망하는 것이 아니며, 단정적인 표현도 쓰지 마라. 감정적 과장 없이 담담한 "
    "어조를 유지하되, 표만 봐서는 알 수 없는 '의미'를 짚어주는 데 집중해 한 문단으로 작성하라."
)


MACRO_ISSUES_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 오늘 수집된 해외(미국/글로벌) 매크로·지정학 뉴스 기사들이다. 이 중 추세추종 투자자가 "
    "오늘 반드시 챙겨야 할 이슈를 3~5개 골라 정리하라. 각 이슈는 번호를 매기고, "
    "(1) 이슈가 무엇인지 한 줄로, (2) 왜 지금 지켜봐야 하는지(연준 통화정책, 금리, 환율, 지정학적 "
    "긴장, 주요 경제지표 발표 등 자산군 전반에 영향을 줄 수 있는 이유)를 근거 기사 내용에 기반해 "
    "구체적으로 설명하라 — 기사 제목만 나열하지 말고 실제로 무슨 내용인지 풀어써라. "
    "이것은 어디까지나 '무엇을 지켜봐야 하는지'에 대한 참고 정리일 뿐이다: 특정 자산의 향후 가격이나 "
    "방향을 예측·전망하지 말고, 단정적인 표현도 쓰지 마라. 이 요약은 어떤 종목의 매수/HOLD/매도 "
    "판정도 바꾸지 않는다. 관련성 높은 이슈가 없다면 그 사실만 담백하게 언급하면 된다. "
    "마크다운 문법(**, ###, ---, 글머리 기호 등)은 전혀 쓰지 말고, 번호와 줄바꿈만으로 구분되는 "
    "평문으로 작성하라 — 이 텍스트는 그대로(마크다운 렌더링 없이) 리포트에 삽입된다."
)


CRYPTO_SPECIAL_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 오늘 수집된 암호화폐 관련 뉴스 기사들이며, 주요 키워드는 RWA(실물자산 토큰화)와 "
    "비트마인(BitMine Immersion Technologies, BMNR — 이더리움을 대규모로 보유하는 상장사)이다. "
    "키워드별로 나눠 정리하라: 각 키워드마다 오늘 기사에서 확인되는 핵심 소식 1~3개를 번호로 적고, "
    "(1) 무슨 일인지 한 줄로, (2) 장기 추세 관점에서 왜 지켜볼 만한지(제도·자금 흐름·이더리움/비트코인 "
    "수급과의 연결 등)를 근거 기사 내용에 기반해 구체적으로 설명하라 — 기사 제목만 나열하지 마라. "
    "단기 가격 소음이나 홍보성 기사는 걸러내라. 특정 자산의 향후 가격이나 방향을 예측·전망하지 말고, "
    "단정적인 표현도 쓰지 마라. 이 정리는 어떤 종목의 매수/HOLD/매도 판정이나 제안 수량도 바꾸지 않는다. "
    "어떤 키워드에 관련 기사가 없다면 그 사실만 담백하게 언급하면 된다. "
    "마크다운 문법(**, ###, ---, 글머리 기호 등)은 전혀 쓰지 말고, 키워드 제목·번호·줄바꿈만으로 "
    "구분되는 평문으로 작성하라 — 이 텍스트는 그대로(마크다운 렌더링 없이) 리포트에 삽입된다."
)


BASEL3_SPECIAL_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 최근 수집된 바젤3(Basel III) 관련 은행 자본·유동성 규제 뉴스이며, 키워드별로 묶여 있다. "
    "이 규제가 채권 평가와 변동성에 어떤 경로로 영향을 주는지를 중심으로 정리하라. 참고할 경로는 다음과 같다: "
    "(1) 평가 — LCR이 국채 등 고유동성자산(HQLA) 보유를 요구해 은행의 국채 수요를 받치는 효과, "
    "SLR 등 레버리지 규제가 국채에도 자본을 부과해 은행의 국채 보유·레포 중개 여력을 줄이고 기간 프리미엄과 "
    "스왑 스프레드에 영향을 주는 효과, 바젤3 최종안의 위험가중자산 산정 변화가 은행 채권 포트폴리오와 "
    "회사채 수요에 미치는 효과; "
    "(2) 변동성 — 딜러 은행의 대차대조표 제약이 시장조성 여력을 낮춰 충격 시 국채 유동성이 마르고 변동성이 "
    "커질 수 있는 구조(예: 2020년 3월 국채시장 혼란과 당시 SLR 한시 완화). "
    "먼저 키워드별로 오늘 기사에서 확인되는 핵심 소식 1~2개를 번호로 적고, 그 소식이 위 경로 중 어디에 "
    "해당하는지, 대표 자산군 중 미국 장기국채(TLT)·중기국채(IEF)를 볼 때 무엇을 지켜볼 만한지를 근거 기사 "
    "내용에 기반해 구체적으로 설명하라. 마지막에 한두 문장으로 규제 흐름이 채권 변동성 환경에 대해 "
    "시사하는 바를 담담하게 요약하라. "
    "채권 가격·금리의 향후 방향을 예측·전망하지 말고, 단정적인 표현도 쓰지 마라. 이 정리는 어떤 종목의 "
    "매수/HOLD/매도 판정이나 제안 수량도 바꾸지 않는다. 어떤 키워드에 관련 기사가 없다면 그 사실만 "
    "담백하게 언급하면 된다. 마크다운 문법(**, ###, ---, 글머리 기호 등)은 전혀 쓰지 말고, 키워드 제목·"
    "번호·줄바꿈만으로 구분되는 평문으로 작성하라 — 이 텍스트는 그대로(마크다운 렌더링 없이) 리포트에 삽입된다."
)


def _format_news_for_prompt(ticker: str, news_items: list[dict]) -> str:
    if not news_items:
        return f"[{ticker}] 관련 금일 뉴스 없음."

    lines = [f"[{ticker}] 종목 뉴스:"]
    for item in news_items:
        lines.append(f"- {item['title']} ({item.get('publisher', '')}): {item.get('summary', '')}")
    return "\n".join(lines)


def _call_chat(system_prompt: str, user_prompt: str) -> str:
    from invest_assistant.storage.runtime import require_private_operation
    require_private_operation()
    if not config.LLM_API_KEY:
        raise ValueError(
            f"No LLM API key set for LLM_PROVIDER={config.LLM_PROVIDER} "
            "(set LLM_API_KEY, OPENAI_API_KEY / OPENAI_KEY for OpenAI, "
            "or OPENROUTER_API_KEY for OpenRouter in .env)"
        )

    response = requests.post(
        config.LLM_BASE_URL.rstrip("/") + CHAT_COMPLETIONS_PATH,
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=config.LLM_REQUEST_TIMEOUT_SEC,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("choices"):
        # OpenRouter's free-tier models occasionally return a 200 with no choices (rate limit,
        # provider hiccup, etc.) instead of a proper error status; OpenAI normally uses real
        # HTTP error codes, but the guard is kept for whichever provider is configured.
        # Surface the actual reason instead of letting a bare KeyError obscure it.
        error_message = (data.get("error") or {}).get("message", str(data)[:300])
        raise RuntimeError(f"{config.LLM_PROVIDER} response missing 'choices': {error_message}")

    message = data["choices"][0].get("message") or {}
    if message.get("refusal"):
        raise RuntimeError(f"{config.LLM_PROVIDER} declined to generate a briefing")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"{config.LLM_PROVIDER} returned an empty briefing")
    return content.strip()


def generate_briefing(ticker: str, news_items: list[dict]) -> str:
    """Ask the configured LLM (as Mr. Serenity) whether today's news is trend-reinforcing or noise."""
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
        category = instrument_universe.ASSET_CLASS_TICKERS.get(ticker, {}).get("category", "")
        lines.append(f"- {ticker} ({category}): {reco['action']} (종가 {reco['close']:.2f})")

    if signal_history:
        lines.append("\n[최근 시그널 이력 (날짜: 자산군=액션, ...)]")
        for date in sorted(signal_history, reverse=True):
            actions_str = ", ".join(f"{ticker}={action}" for ticker, action in signal_history[date].items())
            lines.append(f"- {date}: {actions_str}")

    prompt = "\n".join(lines) + "\n\n위 오늘의 판정과 최근 시그널 이력을 종합해 오늘 시장 상황을 한 문단으로 요약하라."
    return _call_chat(PORTFOLIO_OVERVIEW_SYSTEM_PROMPT, prompt)


def generate_macro_issues_briefing(news_items: list[dict]) -> str:
    """Distill general (non-ticker-specific) macro/geopolitical news into a short numbered
    list of issues a trend-following investor should check today (report_builder's "오늘
    챙겨야 할 해외 이슈" section, fed by recommendation_engine.get_macro_issues_briefing's Exa
    search). Advisory/context only, same as generate_portfolio_overview — never changes any
    ticker's mechanical action.
    """
    prompt = _format_news_for_prompt("해외 매크로", news_items) + "\n\n위 뉴스를 바탕으로 오늘 챙겨야 할 이슈를 정리하라."
    return _call_chat(MACRO_ISSUES_SYSTEM_PROMPT, prompt)


def generate_crypto_special_briefing(news_by_keyword: dict[str, list[dict]]) -> str:
    """Distill keyword-focused crypto news (RWA, BitMine — see news_fetcher.CRYPTO_NEWS_QUERIES)
    into report_builder's crypto special section. Advisory/context only, same as
    generate_macro_issues_briefing — never changes any ticker's mechanical action.
    """
    return _generate_keyword_briefing(CRYPTO_SPECIAL_SYSTEM_PROMPT, news_by_keyword)


def generate_basel3_special_briefing(news_by_keyword: dict[str, list[dict]]) -> str:
    """Distill Basel III regulatory news (news_fetcher.BASEL3_NEWS_QUERIES) into its effect on
    bond valuation and volatility for report_builder's Basel III special section. Advisory only.
    """
    return _generate_keyword_briefing(BASEL3_SPECIAL_SYSTEM_PROMPT, news_by_keyword)


def _generate_keyword_briefing(system_prompt: str, news_by_keyword: dict[str, list[dict]]) -> str:
    blocks = [_format_news_for_prompt(keyword, items) for keyword, items in news_by_keyword.items()]
    prompt = "\n\n".join(blocks) + "\n\n위 뉴스를 키워드별로 정리하라."
    return _call_chat(system_prompt, prompt)


WEEKLY_ASSET_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 지난 한 주(미국 거래일 기준) 대표 자산군 13종의 주간 수익률·고저·트레일링 스탑 거리와, "
    "규칙에 따라 이미 확정된 일별 기계적 판정 기록, 매크로 지표의 주간 변화다. 판정은 확정된 사실이며 "
    "너는 이를 절대 바꾸거나 재해석하지 않는다. 한 주의 소음을 걸러내고 자산군 간 상대적 흐름이 장기 "
    "추세 관점에서 무엇을 의미하는지 담담하게 정리하라. 향후 가격이나 방향을 예측·전망하지 말고 단정적 "
    "표현도 쓰지 마라. 마크다운 문법은 쓰지 말고, 반드시 아래 형식의 줄 머리말을 그대로 지켜 평문으로 "
    "작성하라(각 머리말은 한 번씩만):\n"
    "요약: 한 문장\n"
    "국면: 위험선호, 위험회피, 혼조 중 하나만\n"
    "근거: 두세 문장\n"
    "주식: 두세 문장\n암호화폐: 두세 문장\n귀금속: 두세 문장\n채권: 두세 문장\n원자재: 두세 문장\n통화: 두세 문장"
)

WEEKLY_CHECKPOINTS_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 이번 주 일일 리포트의 '해외 이슈' 정리와 그 근거 기사들이다. 여기에 실제로 언급된 다음 주 "
    "이후의 일정과 이벤트(FOMC, 주요 기업 실적, 경제지표 발표, 정책 결정 등)만 골라 3~6개로 번호를 매겨 "
    "정리하라. 각 항목은 무엇이 언제 예정되어 있는지와 추세추종 투자자가 왜 지켜볼 만한지를 한두 문장으로 "
    "적어라. 자료에 날짜가 없으면 '일정 미확인'이라고 쓰고, 자료에 없는 일정이나 수치는 절대 만들지 마라. "
    "결과를 예측하지 말고, 어떤 종목의 판정도 바꾸지 않는다. 마크다운 없이 번호와 줄바꿈만 쓰는 평문으로 작성하라."
)

WEEKLY_SPECIAL_THEME_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 한 테마({theme})에 대한 이번 주 일별 브리핑과 근거 기사, 주간 추가 검색 기사, 그리고 연결된 "
    "대표 자산의 이번 주 기계적 판정 기록이다. 판정은 확정된 사실이며 너의 해석은 참고용일 뿐 판정을 "
    "바꾸지 않는다. 가격·금리 방향을 예측하지 말고 단정적 표현도 쓰지 마라. 마크다운 없이, 아래 대괄호 "
    "머리말을 각각 한 줄로 단독 배치하고 그 아래에 내용을 쓰라:\n"
    "[반복] 주중 여러 날 반복 등장한 이슈를 번호로 1~3개\n"
    "[신규] 주 후반이나 추가 검색에서 새로 등장한 이슈를 번호로 1~3개\n"
    "[소멸] 주 초반에 다뤄졌다가 이후 사라진 이슈를 번호로 0~3개(없으면 '없음')\n"
    "[수치] 기사에 명시된 수치만 한 줄에 하나씩 '지표 | 값 | 기준일 | 근거 기사 제목' 형식으로. "
    "기사에 없는 수치는 절대 만들거나 계산하지 마라. 없으면 '없음'\n"
    "[자산연결] {assets}의 이번 주 판정 기록과 위 이슈를 연결한 참고 해석 두세 문장\n"
    "[다음주] 다음 주에 지켜볼 점 1~3개"
)

WEEKLY_SPECIAL_HIGHLIGHTS_SYSTEM_PROMPT = (
    "너는 전설적인 시스템 트레이더이자 미스터 세레니티(Mr. Serenity)로 불리는 톰 바소다. "
    "아래는 크립토(RWA·비트마인)와 바젤3(채권 평가·변동성) 테마의 이번 주 정리다. 두 테마를 통틀어 "
    "이번 주 핵심 5가지와 다음 주에 볼 것을 정리하라. 주어진 정리에 없는 사실이나 수치는 만들지 말고, "
    "예측·단정 없이 담담하게 쓰라. 마크다운 없이, 아래 머리말을 각각 한 줄로 단독 배치하라:\n"
    "[핵심] 번호를 매긴 정확히 5개 항목, 각 한두 문장\n"
    "[다음주] 번호를 매긴 2~4개 항목"
)

WEEKLY_ASSET_KEYS = ("요약", "국면", "근거", "주식", "암호화폐", "귀금속", "채권", "원자재", "통화")
WEEKLY_SPECIAL_THEME_KEYS = ("반복", "신규", "소멸", "수치", "자산연결", "다음주")
WEEKLY_SPECIAL_HIGHLIGHT_KEYS = ("핵심", "다음주")


def _parse_prefixed_lines(text: str, keys: tuple[str, ...]) -> dict[str, str]:
    """'키: 내용' lines; untagged lines continue the previous key."""
    pattern = re.compile(r"^\s*(" + "|".join(map(re.escape, keys)) + r")\s*[:：]\s*(.*)$")
    parsed: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        match = pattern.match(line)
        if match and match.group(1) not in parsed:
            current = match.group(1)
            parsed[current] = [match.group(2)]
        elif current is not None:
            parsed[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in parsed.items() if "\n".join(lines).strip()}


def _parse_bracket_sections(text: str, keys: tuple[str, ...]) -> dict[str, str]:
    """'[키]' header lines followed by their body; anything before the first header is dropped."""
    pattern = re.compile(r"^\s*\[(" + "|".join(map(re.escape, keys)) + r")\]\s*(.*)$")
    parsed: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            current = match.group(1)
            parsed.setdefault(current, [])
            if match.group(2).strip():
                parsed[current].append(match.group(2))
        elif current is not None:
            parsed[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in parsed.items() if "\n".join(lines).strip()}


def generate_weekly_asset_briefing(facts: str) -> dict[str, str]:
    """Weekly asset-page overview (요약/국면/근거) and per-category commentary, from the
    pipeline's pre-formatted weekly facts. Keys missing from the reply are simply absent --
    the caller fills them from its rule-based text. Commentary only, never an action."""
    text = _call_chat(WEEKLY_ASSET_SYSTEM_PROMPT, facts + "\n\n위 자료로 지정된 형식에 맞춰 주간 총평을 작성하라.")
    return _parse_prefixed_lines(text, WEEKLY_ASSET_KEYS)


def generate_weekly_checkpoints(daily_issues: list[dict]) -> str:
    """Next-week checkpoints from this week's daily '해외 이슈' records
    ([{"date", "text", "news"}], oldest first; "text" may be empty when only the archived
    news survives)."""
    blocks = []
    for entry in daily_issues:
        block = [f"[{entry['date']} 해외 이슈]"]
        if entry.get("text"):
            block.append(entry["text"])
        block.append(_format_news_for_prompt("근거 기사", entry.get("news") or []))
        blocks.append("\n".join(block))
    prompt = "\n\n".join(blocks) + "\n\n위 자료에 언급된 다음 주 체크포인트를 정리하라."
    return _call_chat(WEEKLY_CHECKPOINTS_SYSTEM_PROMPT, prompt)


def generate_weekly_special_theme(theme: str, assets: str, material: str) -> dict[str, str]:
    """One special theme's weekly synthesis, parsed into WEEKLY_SPECIAL_THEME_KEYS sections.
    `material` is the pipeline-formatted daily records + fresh news + linked asset signals."""
    system_prompt = WEEKLY_SPECIAL_THEME_SYSTEM_PROMPT.format(theme=theme, assets=assets)
    text = _call_chat(system_prompt, material + "\n\n위 자료로 지정된 머리말 형식에 맞춰 정리하라.")
    return _parse_bracket_sections(text, WEEKLY_SPECIAL_THEME_KEYS)


def generate_weekly_special_highlights(theme_summaries: str) -> dict[str, str]:
    text = _call_chat(WEEKLY_SPECIAL_HIGHLIGHTS_SYSTEM_PROMPT, theme_summaries)
    return _parse_bracket_sections(text, WEEKLY_SPECIAL_HIGHLIGHT_KEYS)

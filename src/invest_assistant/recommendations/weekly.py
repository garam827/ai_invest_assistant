"""Weekly report narrative: LLM synthesis with rule-based fallbacks, and special-page inputs.

Every action shown in the weekly report comes from `_signal_history.json`; the LLM text
here is commentary only. Each public function degrades to deterministic text when the
LLM/news call fails or config.SKIP_LLM_AND_NEWS is set, never to a missing action.
"""
from __future__ import annotations

import datetime
import logging
import re

import pandas as pd

from invest_assistant import config
from invest_assistant import universe as instrument_universe
from invest_assistant.analysis import weekly as weekly_calc
from invest_assistant.data import news as news_fetcher
from invest_assistant.recommendations import briefing as llm_briefing
from invest_assistant.recommendations.engine import _collect_keyword_news, load_special_briefings
from invest_assistant.storage.drive import DriveDB

logger = logging.getLogger(__name__)

CATEGORIES = ("주식", "암호화폐", "귀금속", "채권", "원자재", "통화")
WEEKLY_NEWS_LOOKBACK_DAYS = 7
NEWS_SUMMARY_PROMPT_CHARS = 300

THEMES = {
    "crypto": {
        "label": "크립토 (RWA · 비트마인)",
        "assets": ("ETH-USD", "BTC-USD"),
        "queries": news_fetcher.CRYPTO_NEWS_QUERIES,
        "archive_key": news_fetcher.CRYPTO_NEWS_ARCHIVE_KEY,
        "weekly_archive_key": "_WEEKLY_CRYPTO_SPECIAL_",
        "max_items": config.CRYPTO_NEWS_MAX_ITEMS_PER_KEYWORD,
    },
    "basel3": {
        "label": "바젤3 (채권 평가 · 변동성)",
        "assets": ("TLT", "IEF"),
        "queries": news_fetcher.BASEL3_NEWS_QUERIES,
        "archive_key": news_fetcher.BASEL3_NEWS_ARCHIVE_KEY,
        "weekly_archive_key": "_WEEKLY_BASEL3_SPECIAL_",
        "max_items": config.BASEL3_NEWS_MAX_ITEMS_PER_KEYWORD,
    },
}
RECORD_ARCHIVE_KEYS = {
    "crypto": news_fetcher.CRYPTO_NEWS_ARCHIVE_KEY,
    "basel3": news_fetcher.BASEL3_NEWS_ARCHIVE_KEY,
    "macro": news_fetcher.MACRO_NEWS_ARCHIVE_KEY,
}


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:+.2f}%"


def _label(ticker: str) -> str:
    return instrument_universe.ASSET_CLASS_TICKERS.get(ticker, {}).get("label", ticker)


def _category(ticker: str) -> str:
    return instrument_universe.ASSET_CLASS_TICKERS.get(ticker, {}).get("category", "")


def _short_date(day: str) -> str:
    return f"{int(day[5:7])}/{int(day[8:10])}"


def _transition(ticker: str, change: tuple[str, str, str]) -> str:
    day, previous, action = change
    return f"{ticker} {previous}→{action}({_short_date(day)})"


# ---------------------------------------------------------------------------
# Asset page


def format_weekly_facts(window, stats: dict, grid: dict, macro: dict, prev_actions: dict | None = None) -> str:
    lines = [f"[주간 성과 {window.week} ({window.period}), 직전 주 종가 대비]"]
    for ticker, s in stats.items():
        lines.append(
            f"- {ticker} ({_category(ticker)}): 주간 {_fmt_pct(s['return_pct'])}, 주말 종가 {s['close']:.2f}, "
            f"고가 {s['high']:.2f}, 저가 {s['low']:.2f}, 스탑까지 {_fmt_pct(s['stop_distance_pct'])}, "
            f"DC20 상단까지 {_fmt_pct(s['dc20_distance_pct'])}"
        )
    lines.append("\n[일별 기계적 판정 기록 (날짜: 티커=액션; 매도는 종가가 스탑 아래인 동안 매일 기록됨)]")
    if prev_actions:
        lines.append(f"- {window.prev_close_date}(직전 주): " + ", ".join(f"{t}={a}" for t, a in prev_actions.items()))
    for day in sorted(grid):
        lines.append(f"- {day}: " + ", ".join(f"{t}={a or '-'}" for t, a in grid[day].items()))
    if macro:
        lines.append("\n[매크로 주간 변화 (직전 주 종가 → 주말)]")
        for item in macro.values():
            lines.append(f"- {item['label']}: {item['start_value']:.3f} → {item['end_value']:.3f}")
    return "\n".join(lines)


def rule_based_asset_briefing(window, stats: dict, changes: dict) -> dict[str, str]:
    ranked = sorted(stats, key=lambda t: stats[t]["return_pct"], reverse=True)
    regime, risk, safe = weekly_calc.rule_based_regime(stats)
    best, worst = ranked[0], ranked[-1]
    events = ", ".join(_transition(t, item) for t, items in changes.items() for item in items) or "없음"
    briefing = {
        "요약": (
            f"{window.period} 한 주 동안 {best}가 {_fmt_pct(stats[best]['return_pct'])}로 가장 강했고 "
            f"{worst}가 {_fmt_pct(stats[worst]['return_pct'])}로 가장 약했습니다."
        ),
        "국면": regime,
        "근거": (
            f"위험자산(SPY·QQQ·BTC·ETH) 평균 {_fmt_pct(risk)}, 안전자산(TLT·IEF·UUP) 평균 {_fmt_pct(safe)} "
            f"기준의 규칙 기반 분류입니다. 이번 주 시그널 전환: {events}."
        ),
    }
    for category in CATEGORIES:
        tickers = [t for t in stats if _category(t) == category]
        if not tickers:
            continue
        parts = ", ".join(f"{t} {_fmt_pct(stats[t]['return_pct'])}" for t in tickers)
        signals = [_transition(t, item) for t in tickers for item in changes.get(t, [])]
        note = f" 시그널 전환: {', '.join(signals)}." if signals else " 이번 주 시그널 전환은 없습니다."
        briefing[category] = f"주간 수익률 {parts}.{note}"
    return briefing


def get_weekly_asset_briefing(
    window, stats: dict, grid: dict, changes: dict, macro: dict, prev_actions: dict | None = None
) -> tuple[dict, str]:
    """(briefing, source) where source is "llm" or "rule". Missing/invalid LLM fields are
    filled from the rule-based text so every section always renders."""
    fallback = rule_based_asset_briefing(window, stats, changes)
    if config.SKIP_LLM_AND_NEWS:
        return fallback, "rule"
    try:
        parsed = llm_briefing.generate_weekly_asset_briefing(
            format_weekly_facts(window, stats, grid, macro, prev_actions)
        )
    except Exception:
        logger.exception("Weekly asset LLM briefing failed; using the rule-based text")
        return fallback, "rule"
    if parsed.get("국면") not in weekly_calc.REGIMES:
        parsed.pop("국면", None)
    if not parsed.get("요약"):
        return fallback, "rule"
    return {**fallback, **parsed}, "llm"


# ---------------------------------------------------------------------------
# Stored daily briefings (special sections + macro issues)


def collect_daily_records(drive_db: DriveDB, window) -> dict[str, dict[str, dict]]:
    """{"crypto"|"basel3"|"macro": {date: {"text", "news"}}} for the week's trading days.

    Prefers `_special_briefings.json`; a day missing there (before the accumulator existed,
    or a failed save) falls back to the news archived that calendar day (text empty).
    """
    stored = load_special_briefings(drive_db)
    records: dict[str, dict[str, dict]] = {name: {} for name in RECORD_ARCHIVE_KEYS}
    for day in window.trading_days:
        entry = stored.get(day) or {}
        archive = None
        for name, archive_key in RECORD_ARCHIVE_KEYS.items():
            section = entry.get(name)
            if section and section.get("text"):
                records[name][day] = {"text": section["text"], "news": section.get("news") or []}
                continue
            if archive is None:
                archive = drive_db.load_json(f"{news_fetcher.NEWS_ARCHIVE_PREFIX}{day}.json") or {}
            if archive.get(archive_key):
                records[name][day] = {"text": "", "news": archive[archive_key]}
    return records


def rule_based_checkpoints(macro_records: dict[str, dict]) -> str:
    texts = [f"({_short_date(d)}) {r['text']}" for d, r in sorted(macro_records.items()) if r.get("text")]
    if not texts:
        return "이번 주 일일 리포트에 저장된 해외 이슈 정리가 없어 다음 주 체크포인트를 만들지 못했습니다."
    return "LLM 정리 없이 이번 주 일일 해외 이슈 원문을 그대로 옮깁니다.\n\n" + "\n\n".join(texts)


def get_weekly_checkpoints(macro_records: dict[str, dict]) -> tuple[str, str]:
    if config.SKIP_LLM_AND_NEWS or not macro_records:
        return rule_based_checkpoints(macro_records), "rule"
    entries = [{"date": d, **r} for d, r in sorted(macro_records.items())]
    try:
        return llm_briefing.generate_weekly_checkpoints(entries), "llm"
    except Exception:
        logger.exception("Weekly checkpoints LLM call failed; using the stored daily text")
        return rule_based_checkpoints(macro_records), "rule"


# ---------------------------------------------------------------------------
# Special page


def fetch_fresh_theme_news(drive_db: DriveDB, theme: str) -> list[dict]:
    spec = THEMES[theme]
    return _collect_keyword_news(
        drive_db, spec["weekly_archive_key"], spec["queries"], spec["max_items"], WEEKLY_NEWS_LOOKBACK_DAYS
    )


def _news_key(item: dict) -> str:
    return item.get("link") or item.get("title") or ""


def _news_line(item: dict) -> str:
    summary = (item.get("summary") or "")[:NEWS_SUMMARY_PROMPT_CHARS]
    return f"- {item.get('title', '')} ({item.get('publisher', '')}): {summary}"


def _asset_signal_lines(assets, stats: dict, grid: dict) -> list[str]:
    lines = []
    for ticker in assets:
        if ticker not in stats:
            continue
        actions = ", ".join(f"{_short_date(d)} {grid[d].get(ticker) or '-'}" for d in sorted(grid))
        lines.append(f"- {ticker}: 주간 {_fmt_pct(stats[ticker]['return_pct'])}; {actions}")
    return lines


def format_theme_material(daily: dict[str, dict], fresh: list[dict], signal_lines: list[str]) -> str:
    lines = ["[일별 브리핑]"]
    if not daily:
        lines.append("저장된 일별 브리핑 없음")
    for day, record in sorted(daily.items()):
        lines.append(f"({day}) {record.get('text') or '브리핑 텍스트 없음(기사만 보관)'}")
        lines += [f"  {_news_line(item)}" for item in record.get("news") or []]
    lines.append("\n[주간 추가 검색 기사(최근 7일)]")
    lines += [_news_line(item) for item in fresh] or ["없음"]
    lines.append("\n[연결 자산의 이번 주 기계적 판정 기록]")
    lines += signal_lines or ["없음"]
    return "\n".join(lines)


def _theme_corpus(daily: dict[str, dict], fresh: list[dict]) -> str:
    parts = []
    for record in daily.values():
        parts.append(record.get("text") or "")
        parts += [f"{i.get('title', '')} {i.get('summary', '')}" for i in record.get("news") or []]
    parts += [f"{i.get('title', '')} {i.get('summary', '')}" for i in fresh]
    return "\n".join(parts)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+")


def verify_number_rows(text: str, corpus: str) -> tuple[list[dict], int]:
    """Keep 'metric | value | as-of | source' rows whose every number appears in the source
    corpus (commas ignored); a row with no number or a number absent from the articles is
    dropped. Returns (rows, dropped_count)."""
    corpus_plain = corpus.replace(",", "")
    rows, dropped = [], 0
    for line in text.splitlines():
        line = _LIST_MARKER.sub("", line).strip()
        if not line or line == "없음":
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) != 4:
            dropped += 1
            continue
        metric, value, as_of, source = cells
        numbers = [n.replace(",", "") for n in _NUMBER.findall(value)]
        if not numbers or any(n not in corpus_plain for n in numbers):
            dropped += 1
            continue
        rows.append({"metric": metric, "value": value, "as_of": as_of, "source": source})
    return rows, dropped


def rule_based_theme(daily: dict[str, dict], fresh: list[dict], assets, stats: dict, grid: dict) -> dict:
    """Article-recurrence flows by link: recurring (2+ days, still present on the last
    recorded day), new (first seen on the last day or only in the fresh search),
    faded (last seen before the last recorded day)."""
    seen: dict[str, dict] = {}
    days = sorted(daily)
    for day in days:
        for item in daily[day].get("news") or []:
            entry = seen.setdefault(_news_key(item), {"item": item, "days": set()})
            entry["days"].add(day)
    fresh_keys = {_news_key(i) for i in fresh}
    for item in fresh:
        seen.setdefault(_news_key(item), {"item": item, "days": set()})

    last_day = days[-1] if days else None
    recurring, new, faded = [], [], []
    for key, entry in seen.items():
        present_at_end = last_day in entry["days"] or key in fresh_keys
        title = entry["item"].get("title", "")
        if len(entry["days"]) >= 2 and present_at_end:
            recurring.append(title)
        elif present_at_end and (not entry["days"] or min(entry["days"]) == last_day):
            new.append(title)
        elif not present_at_end:
            faded.append(title)

    def _numbered(titles):
        return "\n".join(f"{n}. {t}" for n, t in enumerate(titles[:5], 1)) or "없음"

    signals = _asset_signal_lines(assets, stats, grid)
    return {
        "반복": _numbered(recurring),
        "신규": _numbered(new),
        "소멸": _numbered(faded),
        "자산연결": "연결 자산의 이번 주 기록된 판정(참고용, 해석 없음):\n" + ("\n".join(signals) or "없음"),
        "다음주": "반복 등장한 기사 주제가 다음 주에도 이어지는지 확인하세요.",
        "_titles": recurring + new,
    }


def build_weekly_special(
    drive_db: DriveDB, window, records: dict, stats: dict, grid: dict, fresh_search: bool
) -> dict | None:
    """Inputs + synthesis for the special page; None when there is nothing to synthesize.
    `fresh_search` is False for `--week` reruns (Exa is relative to now and would leak
    later articles into a past week)."""
    themes = {}
    for name, spec in THEMES.items():
        daily = records.get(name, {})
        fresh: list[dict] = []
        if fresh_search:
            try:
                fresh = fetch_fresh_theme_news(drive_db, name)
            except Exception:
                logger.exception("Weekly %s fresh news search failed; using stored records only", name)
        news, seen = [], set()
        for item in [i for d in sorted(daily) for i in daily[d].get("news") or []] + fresh:
            if _news_key(item) not in seen:
                seen.add(_news_key(item))
                news.append(item)
        themes[name] = {
            "label": spec["label"], "assets": spec["assets"], "daily": daily, "fresh": fresh,
            "news": news, "record_days": sorted(daily), "texts_days": sorted(d for d, r in daily.items() if r.get("text")),
        }
    if not any(t["news"] or t["texts_days"] for t in themes.values()):
        logger.info("No stored or fresh special-section material for %s; skipping the special page", window.week)
        return None

    sources = []
    for name, theme in themes.items():
        signals = _asset_signal_lines(theme["assets"], stats, grid)
        fallback = rule_based_theme(theme["daily"], theme["fresh"], theme["assets"], stats, grid)
        sections, source = fallback, "rule"
        if theme["news"] or theme["texts_days"]:
            try:
                parsed = llm_briefing.generate_weekly_special_theme(
                    theme["label"], "·".join(theme["assets"]),
                    format_theme_material(theme["daily"], theme["fresh"], signals),
                )
                if parsed:
                    sections, source = {**fallback, **parsed}, "llm"
            except Exception:
                logger.exception("Weekly %s special LLM call failed; using the rule-based flows", name)
        if source == "llm":
            rows, dropped = verify_number_rows(sections.get("수치", ""), _theme_corpus(theme["daily"], theme["fresh"]))
        else:
            rows, dropped = [], 0
        theme.update(
            flows={k: sections[k] for k in ("반복", "신규", "소멸")}, numbers=rows, numbers_dropped=dropped,
            connection=sections["자산연결"], next_week=sections["다음주"], source=source,
            fallback_titles=fallback["_titles"],
        )
        sources.append(source)

    highlights, next_week, source = None, None, "rule"
    if "llm" in sources:
        summary = "\n\n".join(
            f"[{t['label']}]\n반복: {t['flows']['반복']}\n신규: {t['flows']['신규']}\n소멸: {t['flows']['소멸']}\n"
            f"자산 연결: {t['connection']}\n다음 주: {t['next_week']}"
            for t in themes.values()
        )
        try:
            parsed = llm_briefing.generate_weekly_special_highlights(summary)
            highlights, next_week = parsed.get("핵심"), parsed.get("다음주")
            source = "llm" if highlights else "rule"
        except Exception:
            logger.exception("Weekly special highlights LLM call failed; using rule-based highlights")
    if not highlights:
        titles = [title for t in themes.values() for title in t["fallback_titles"]][:5]
        highlights = "\n".join(f"{n}. {title}" for n, title in enumerate(titles, 1)) or "정리할 핵심 기사가 없습니다."
    if not next_week:
        next_week = "\n".join(f"{t['label']}: {t['next_week']}" for t in themes.values())
    return {"themes": themes, "highlights": highlights, "next_week": next_week, "source": source}


def now_eastern_date() -> datetime.date:
    return pd.Timestamp.now(tz="America/New_York").date()

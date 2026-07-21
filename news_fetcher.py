"""News collection for tickers analyzed by the LLM recommendation flow.

fetch_ticker_news_exa (Exa's neural search API, https://exa.ai, scoped to news sites) is the
only source — output shape: list of {title, summary, publisher, link, published_at}. An
earlier yfinance-based fetcher was fully replaced by this (see spec changelog v2.7) and has
been removed rather than kept as an unused parallel implementation.
"""
from __future__ import annotations

import datetime
from urllib.parse import urlparse

import requests

import config

NEWS_ARCHIVE_PREFIX = "_news_"
EXA_SEARCH_URL = "https://api.exa.ai/search"


def fetch_ticker_news_exa(
    ticker: str,
    query: str | None = None,
    max_items: int = config.NEWS_MAX_ITEMS_PER_TICKER,
    lookback_days: int = config.EXA_NEWS_LOOKBACK_DAYS,
) -> list[dict]:
    """Fetch recent news for a ticker via the Exa search API (neural search, scoped to news sites)."""
    if not config.EXA_API_KEY:
        raise ValueError("EXA_API_KEY is not set")

    start_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    response = requests.post(
        EXA_SEARCH_URL,
        headers={"x-api-key": config.EXA_API_KEY, "Content-Type": "application/json"},
        json={
            "query": query or f"{ticker} stock news",
            "type": "auto",
            "category": "news",
            "numResults": max_items,
            "startPublishedDate": start_date,
            "contents": {"summary": True},
        },
        timeout=30,
    )
    response.raise_for_status()
    results = response.json().get("results", [])

    items = []
    for result in results:
        link = result.get("url", "")
        title = result.get("title")
        if not title:
            continue
        items.append(
            {
                "title": title,
                "summary": result.get("summary", ""),
                "publisher": result.get("author") or urlparse(link).netloc,
                "link": link,
                "published_at": result.get("publishedDate"),
            }
        )
    return items


def get_cached_news(drive_db, ticker: str, date: str | None = None) -> list[dict] | None:
    """Read-through cache check against the same per-date archive archive_news writes to.

    Returns the cached list if this ticker already has news archived for `date` (defaults
    to today), or None if there's nothing cached yet — callers should fetch from Exa in that
    case and archive_news() the result. Distinct multi-user callers (e.g. the Streamlit UI)
    requesting the same ticker on the same day share one Exa call instead of paying for it
    per visitor.
    """
    date = date or datetime.date.today().isoformat()
    archive = drive_db.load_json(f"{NEWS_ARCHIVE_PREFIX}{date}.json") or {}
    cached = archive.get(ticker)
    return cached if cached else None


def archive_news(drive_db, ticker: str, news_items: list[dict], date: str | None = None) -> list[dict]:
    """Persist news used for LLM analysis to a per-date Drive JSON archive (one file per
    calendar date, `{ticker: [news_item, ...]}`), deduped by article link (falls back to
    title if a link is missing) so re-runs on the same day don't store duplicates.

    Returns the ticker's merged (pre-existing + newly added) list for that date.
    """
    date = date or datetime.date.today().isoformat()
    filename = f"{NEWS_ARCHIVE_PREFIX}{date}.json"

    archive = drive_db.load_json(filename) or {}
    existing = archive.get(ticker, [])
    existing_keys = {item.get("link") or item.get("title") for item in existing}

    new_items = [item for item in news_items if (item.get("link") or item.get("title")) not in existing_keys]
    if not new_items:
        return existing

    archive[ticker] = existing + new_items
    drive_db.save_json(filename, archive)
    return archive[ticker]

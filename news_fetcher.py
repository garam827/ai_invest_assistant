"""News collection for tickers analyzed by the LLM recommendation flow.

Two sources, same output shape (list of {title, summary, publisher, link, published_at}):
- fetch_ticker_news: yfinance's built-in news feed (Ticker.news).
- fetch_ticker_news_exa: Exa's neural search API (https://exa.ai), scoped to news sites —
  this is what app.py's recommendation flow actually calls.
"""
from __future__ import annotations

import datetime
import logging
from urllib.parse import urlparse

import requests
import yfinance as yf

import config

logger = logging.getLogger(__name__)

NEWS_ARCHIVE_PREFIX = "_news_"
EXA_SEARCH_URL = "https://api.exa.ai/search"


def fetch_ticker_news(ticker: str, max_items: int = config.NEWS_MAX_ITEMS_PER_TICKER) -> list[dict]:
    """Fetch recent text-article headlines/summaries for a ticker (video items are skipped)."""
    raw_news = yf.Ticker(ticker).news or []

    items = []
    for entry in raw_news:
        content = entry.get("content", {})
        if content.get("contentType") != "STORY":
            continue
        title = content.get("title")
        if not title:
            continue

        items.append(
            {
                "title": title,
                "summary": content.get("summary", ""),
                "publisher": (content.get("provider") or {}).get("displayName", ""),
                "link": (content.get("canonicalUrl") or {}).get("url", ""),
                "published_at": content.get("pubDate"),
            }
        )
        if len(items) >= max_items:
            break

    return items


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


def fetch_news_for_tickers(tickers: list[str]) -> dict[str, list[dict]]:
    """Fetch news for each ticker in a signal list. Missing/failed lookups map to an empty list."""
    news_by_ticker: dict[str, list[dict]] = {}
    for ticker in tickers:
        try:
            news_by_ticker[ticker] = fetch_ticker_news(ticker)
        except Exception:
            logger.exception("Failed to fetch news for %s", ticker)
            news_by_ticker[ticker] = []
    return news_by_ticker


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

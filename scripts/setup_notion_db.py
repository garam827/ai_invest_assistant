"""One-off creation of the two Notion databases the daily publication mirrors into.

Run once with an integration token; it prints the two database IDs to put in .env /
GitHub Secrets. The daily pipeline never creates a database — it only writes rows into
the IDs this script produces, so re-running it is never part of a cron path.

    python scripts/setup_notion_db.py --dry-run   # print the schema, call nothing
    python scripts/setup_notion_db.py             # create both databases

Requires NOTION_API_KEY and NOTION_PARENT_PAGE_ID, and the parent page must be shared
with the integration (Notion page -> ... -> Connections -> add the integration), or the
create call fails with "Could not find page with ID".
"""
from __future__ import annotations

import argparse
import json
import sys

import requests

from invest_assistant import config
from invest_assistant import universe as instrument_universe

if hasattr(sys.stdout, "reconfigure"):  # Korean property names on a cp949 console
    sys.stdout.reconfigure(encoding="utf-8")

NOTION_API = "https://api.notion.com/v1"
# Pinned deliberately: 2025-09-03 reorganised databases behind "data sources" and changes
# both the create payload and the query path. Nothing here needs that, and pinning keeps
# this script and publishing/notion.py on one contract.
NOTION_VERSION = "2022-06-28"

ACTION_COLORS = {"매수": "green", "HOLD": "default", "매도": "red"}
CATEGORY_COLORS = {
    "주식": "blue",
    "암호화폐": "orange",
    "귀금속": "yellow",
    "채권": "purple",
    "원자재": "brown",
    "통화": "gray",
}


def _headers() -> dict:
    if not config.NOTION_API_KEY:
        raise ValueError("NOTION_API_KEY is not set")
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _select_options(values: list[str], colors: dict[str, str]) -> dict:
    return {"options": [{"name": v, "color": colors.get(v, "default")} for v in values]}


def reports_schema() -> dict:
    """1 row = 1 business day. Mirrors what recommend.py already computes for Telegram:
    the published report URL plus the cross-asset overview and the action tally."""
    return {
        "리포트": {"title": {}},  # "2026-09-17"
        "일자": {"date": {}},
        "리포트 URL": {"url": {}},
        "총평": {"rich_text": {}},
        "매수": {"number": {"format": "number"}},
        "HOLD": {"number": {"format": "number"}},
        "매도": {"number": {"format": "number"}},
        "발행 시각": {"date": {}},
    }


def signals_schema(reports_db_id: str) -> dict:
    """1 row = 1 day x 1 representative asset (12/day). Deliberately not the S&P 500 sweep:
    the daily batch recommendation scope is the representative assets, and 275 rows/day
    would take ~90s alone against Notion's 3 req/s limit."""
    tickers = list(instrument_universe.ASSET_CLASS_TICKERS)
    categories = sorted({m.get("category", "") for m in instrument_universe.ASSET_CLASS_TICKERS.values()})
    return {
        "시그널": {"title": {}},  # "2026-09-17 SPY"
        "일자": {"date": {}},
        "티커": {"select": _select_options(tickers, {})},
        "자산군": {"select": _select_options(categories, CATEGORY_COLORS)},
        "이름": {"rich_text": {}},
        "판정": {"select": _select_options(["매수", "HOLD", "매도"], ACTION_COLORS)},
        "종가": {"number": {"format": "dollar"}},
        "설명": {"rich_text": {}},
        "뉴스": {"number": {"format": "number"}},
        "리포트": {"relation": {"database_id": reports_db_id, "single_property": {}}},
    }


def create_database(title: str, properties: dict) -> str:
    payload = {
        "parent": {"type": "page_id", "page_id": config.NOTION_PARENT_PAGE_ID},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }
    response = requests.post(f"{NOTION_API}/databases", headers=_headers(), json=payload, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Notion refused to create {title!r}: {response.status_code} {response.text}")
    return response.json()["id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the schema without calling Notion")
    args = parser.parse_args()

    if args.dry_run:
        print(json.dumps({"리포트 인덱스": reports_schema()}, ensure_ascii=False, indent=2))
        print(json.dumps({"시그널 로그": signals_schema("<리포트 인덱스 DB ID>")}, ensure_ascii=False, indent=2))
        return

    if not config.NOTION_PARENT_PAGE_ID:
        raise ValueError("NOTION_PARENT_PAGE_ID is not set")
    if config.NOTION_REPORTS_DB_ID or config.NOTION_SIGNALS_DB_ID:
        raise SystemExit(
            "NOTION_REPORTS_DB_ID/NOTION_SIGNALS_DB_ID already set — refusing to create a second "
            "pair of databases. Unset them to start over."
        )

    reports_db_id = create_database("투자 리포트 인덱스", reports_schema())
    print(f"NOTION_REPORTS_DB_ID={reports_db_id}")
    # Created second so its 리포트 relation can point at the index above.
    signals_db_id = create_database("자산군 시그널 로그", signals_schema(reports_db_id))
    print(f"NOTION_SIGNALS_DB_ID={signals_db_id}")
    print("\nAdd both lines to .env (and to GitHub Secrets for the scheduled run).")


if __name__ == "__main__":
    main()

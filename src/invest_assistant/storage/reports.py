"""Persist and retrieve daily reports."""
from __future__ import annotations

import os

from invest_assistant.paths import REPORT_DIR

REPORT_FILENAME_PREFIX = "_report_"
LOCAL_REPORT_DIR = str(REPORT_DIR)

def save_report(drive_db, date: str, report_html: str) -> None:
    """Persist the report to Drive (for the Streamlit history tab) and write a local
    docs/reports/{date}.html file for recommend.yml to commit+push to GitHub Pages.

    Test publishes (config.IS_TEST_REPORT, `date` already ends with "_test" by the time
    it reaches here) are now also written to docs/reports/ and published (v3.52, reversing
    v3.27's Drive-only restriction, per explicit user request) — the "_test" suffix carries
    through to the local filename and public URL too (e.g. docs/reports/2026-08-10_test.html),
    so a test publish still can never collide with or overwrite that day's real report; it's
    simply also reachable as its own distinct public page instead of only via Drive/the
    Streamlit download button. `list_report_dates` still excludes "_test" dates from the
    Streamlit history table's main grid (see that function) — this only changes whether the
    file reaches GitHub Pages, not whether it's listed there.
    """
    drive_db.save_text(f"{REPORT_FILENAME_PREFIX}{date}.html", report_html)

    os.makedirs(LOCAL_REPORT_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_REPORT_DIR, f"{date}.html"), "w", encoding="utf-8") as f:
        f.write(report_html)


def list_report_dates(drive_db) -> list[str]:
    """Dates (YYYY-MM-DD, newest first) with a saved *real* report in Drive — manual/sample
    test publishes (config.IS_TEST_REPORT, "{date}_test") are excluded so the Streamlit
    history list only ever shows genuine daily reports."""
    filenames = drive_db.list_filenames(REPORT_FILENAME_PREFIX)
    dates = [f.removeprefix(REPORT_FILENAME_PREFIX).removesuffix(".html") for f in filenames]
    dates = [d for d in dates if not d.endswith("_test")]
    return sorted(dates, reverse=True)


def list_test_report_dates(drive_db) -> list[str]:
    """List test report dates, including the suffix used by their public HTML files."""
    filenames = drive_db.list_filenames(REPORT_FILENAME_PREFIX)
    dates = [f.removeprefix(REPORT_FILENAME_PREFIX).removesuffix(".html") for f in filenames]
    dates = [d for d in dates if d.endswith("_test")]
    return sorted(dates, reverse=True)


def load_report(drive_db, date: str) -> str | None:
    return drive_db.load_text(f"{REPORT_FILENAME_PREFIX}{date}.html")

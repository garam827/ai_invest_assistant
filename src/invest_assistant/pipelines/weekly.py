"""Weekly asset and special-section reports, static index, and Telegram summary.

python -m invest_assistant.pipelines.weekly [--week YYYY-Www]

The scheduled run targets the most recent completed US trading week and fails before
publishing when that week's data is stale. `--week` regenerates a past week without
Telegram or a fresh Exa search, and reads nothing dated after the week's last trading day.
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os

from invest_assistant import config
from invest_assistant import universe as instrument_universe
from invest_assistant.analysis import weekly as weekly_calc
from invest_assistant.data import market as data_fetcher
from invest_assistant.publishing import static as static_export
from invest_assistant.publishing import telegram as telegram_notifier
from invest_assistant.recommendations import weekly as weekly_briefing
from invest_assistant.recommendations.engine import load_signal_history
from invest_assistant.reporting import weekly as weekly_report
from invest_assistant.storage import reports as report_store
from invest_assistant.storage.drive import DriveDB

logger = logging.getLogger(__name__)

ANCHOR_TICKER = "SPY"


def _load_frames(drive_db: DriveDB, tickers) -> dict:
    frames = {}
    for ticker in tickers:
        raw_df = drive_db.load_ticker(ticker)
        if raw_df is None or raw_df.empty:
            raise RuntimeError(f"No stored data for {ticker}; refusing to publish the weekly report")
        frames[ticker] = raw_df
    return frames


def _macro_changes(window) -> dict:
    start = (weekly_calc.parse_week(window.week)[0] - datetime.timedelta(days=10)).isoformat()
    try:
        closes = data_fetcher.fetch_macro_history(start, window.last_day)
    except Exception:
        logger.exception("Failed to fetch macro history (section omitted)")
        return {}
    changes = {}
    for ticker, meta in instrument_universe.MACRO_TICKERS.items():
        if ticker not in closes:
            continue
        change = weekly_calc.macro_week_change(closes[ticker], window)
        if change:
            changes[ticker] = {**meta, **change}
    return changes


def _daily_links(window) -> list[tuple[str, str]]:
    return [
        (day, f"../{day}.html")
        for day in window.trading_days
        if os.path.exists(os.path.join(report_store.LOCAL_REPORT_DIR, f"{day}.html"))
    ]


def run_weekly_report(drive_db: DriveDB, week: str | None = None) -> dict:
    """Build and publish both weekly pages. Returns a summary dict (week, paths, urls)."""
    historical = week is not None
    latest = weekly_calc.default_target_week(weekly_briefing.now_eastern_date())
    target = week or latest
    weekly_calc.parse_week(target)
    if target > latest:
        raise ValueError(f"{target} has not finished yet; the latest completed week is {latest}")
    suffix = "_test" if config.IS_TEST_REPORT else ""
    logger.info("Weekly report for %s (historical=%s, test=%s)", target, historical, config.IS_TEST_REPORT)

    tickers = list(instrument_universe.ASSET_CLASS_TICKERS)
    frames = _load_frames(drive_db, tickers)
    window = weekly_calc.resolve_week_window(target, frames[ANCHOR_TICKER])
    history = {d: v for d, v in load_signal_history(drive_db).items() if d <= window.last_day}
    for message in weekly_calc.check_freshness(window, frames, history, strict=not historical):
        logger.warning("Weekly data warning: %s", message)

    stats = {ticker: weekly_calc.compute_asset_week(frames[ticker], window) for ticker in tickers}
    grid = weekly_calc.week_signal_grid(history, window, tickers)
    prev_actions = {t: a for t, a in history.get(window.prev_close_date, {}).items() if t in frames}
    changes = weekly_calc.signal_changes(grid, prev_actions)
    macro = _macro_changes(window)

    records = weekly_briefing.collect_daily_records(drive_db, window)
    briefing, briefing_source = weekly_briefing.get_weekly_asset_briefing(
        window, stats, grid, changes, macro, prev_actions
    )
    checkpoints, checkpoints_source = weekly_briefing.get_weekly_checkpoints(records.get("macro", {}))

    special = None
    if config.SKIP_LLM_AND_NEWS:
        logger.info("SKIP_LLM_AND_NEWS set: skipping the weekly special-section page")
    else:
        special = weekly_briefing.build_weekly_special(
            drive_db, window, records, stats, grid, fresh_search=not historical
        )

    asset_name = f"{window.week}{suffix}"
    special_name = f"{window.week}-special{suffix}"
    result = {"week": window.week, "period": window.period, "asset_path": None, "special_path": None}

    if special is not None:
        special_html = weekly_report.build_weekly_special_html(window, special, stats, grid, f"{asset_name}.html")
        result["special_path"] = report_store.save_weekly_report(drive_db, special_name, special_html)

    asset_html = weekly_report.build_weekly_asset_html(
        window, stats, grid, changes, prev_actions, briefing, briefing_source, macro, checkpoints, checkpoints_source,
        frames, _daily_links(window), f"{special_name}.html" if special is not None else None,
    )
    result["asset_path"] = report_store.save_weekly_report(drive_db, asset_name, asset_html)
    logger.info("Saved weekly report pages: %s, %s", result["asset_path"], result["special_path"])

    try:
        static_export.export_weekly_reports_index(window.week, window.period)
    except Exception:
        logger.exception("Failed to export weekly_reports.json (pages already saved)")

    _write_github_output(window.week)

    if historical or config.IS_TEST_REPORT:
        logger.info("Historical or test weekly run: Telegram skipped")
    elif config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        base = f"{config.REPORT_BASE_URL}/weekly"
        try:
            telegram_notifier.send_message(
                telegram_notifier.format_weekly_summary(
                    window.week, window.period, briefing.get("요약", ""), briefing.get("국면", "혼조"),
                    {t: s["return_pct"] for t, s in stats.items()}, changes,
                    f"{base}/{asset_name}.html", f"{base}/{special_name}.html" if special is not None else None,
                )
            )
        except Exception:
            logger.exception("Failed to send the weekly Telegram summary (pages already published)")
    else:
        logger.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set, skipping Telegram notification")
    return result


def _write_github_output(week: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"week={week}\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--week", metavar="YYYY-Www",
        help="regenerate a past ISO week (no Telegram, no fresh news search); omit for the latest completed week",
    )
    args = parser.parse_args(argv)
    if args.week:
        weekly_calc.parse_week(args.week)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_weekly_report(DriveDB(), week=args.week)


if __name__ == "__main__":
    main()

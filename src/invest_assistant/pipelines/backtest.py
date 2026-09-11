"""Manual backtest execution and result publication."""
import os
import sys

from invest_assistant import config
from invest_assistant.analysis.backtest import (
    BACKTEST_CACHE_DIR,
    BACKTEST_SUMMARY_FILENAME,
    RECENT_YEARS,
    build_backtest_summary,
    build_full_universe,
    calculate_kelly_fraction,
    run_backtest,
    save_backtest_summary_to_drive,
    simulate_equity_curve,
    simulate_trades,
    summarize_hit_rates,
    summarize_trades,
)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "full-universe":
        from invest_assistant.storage.drive import DriveDB

        db = DriveDB()
        universe = build_full_universe(db)
        print(f"Backtesting {len(universe)} tickers (full history + last {RECENT_YEARS}y)...")
        summary = build_backtest_summary(universe)
        os.makedirs(BACKTEST_CACHE_DIR, exist_ok=True)
        summary_path = os.path.join(BACKTEST_CACHE_DIR, "backtest_summary.csv")
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        print(f"{len(summary)} tickers summarized, saved to {summary_path}")
        save_backtest_summary_to_drive(db, summary)
        print(f"Uploaded to Drive as {BACKTEST_SUMMARY_FILENAME}")
        raise SystemExit(0)

    os.makedirs(BACKTEST_CACHE_DIR, exist_ok=True)

    results = run_backtest()
    summary = summarize_hit_rates(results)
    hit_rate_path = os.path.join(BACKTEST_CACHE_DIR, "hit_rates_summary.csv")
    summary.to_csv(hit_rate_path, index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"\nsaved to: {hit_rate_path}")

    trades = simulate_trades()
    trade_summary = summarize_trades(trades)
    trades_path = os.path.join(BACKTEST_CACHE_DIR, "trades.csv")
    trade_summary_path = os.path.join(BACKTEST_CACHE_DIR, "trade_summary.csv")
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    trade_summary.to_csv(trade_summary_path, index=False, encoding="utf-8-sig")
    print()
    print(trade_summary.to_string(index=False))
    print(f"\nsaved to: {trades_path}, {trade_summary_path}")

    kelly = calculate_kelly_fraction(trades)
    print()
    print("Kelly:", kelly)

    default_trades, default_curve_summary = simulate_equity_curve(risk_pct=config.DEFAULT_RISK_PCT)
    print(f"\nEquity curve @ risk_pct={config.DEFAULT_RISK_PCT:.1%} (production default):", default_curve_summary)

    if kelly["half_kelly_fraction_pct"] is not None and kelly["half_kelly_fraction_pct"] > 0:
        half_kelly_risk_pct = kelly["half_kelly_fraction_pct"] / 100
        kelly_trades, kelly_curve_summary = simulate_equity_curve(risk_pct=half_kelly_risk_pct)
        print(f"Equity curve @ risk_pct={half_kelly_risk_pct:.1%} (half-Kelly):", kelly_curve_summary)
        equity_path = os.path.join(BACKTEST_CACHE_DIR, "equity_curve_half_kelly.csv")
        kelly_trades.to_csv(equity_path, index=False, encoding="utf-8-sig")
        print(f"saved to: {equity_path}")
    else:
        default_trades.to_csv(os.path.join(BACKTEST_CACHE_DIR, "equity_curve_default.csv"), index=False, encoding="utf-8-sig")

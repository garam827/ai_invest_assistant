# Repository guidance

Current specification: [v3.64](documentation/specs/investment_assistant_spec.md).
Architecture and migration map: [layout](documentation/architecture/layout.md).
Historical notes are preserved in `documentation/specs/archive/`; they describe older paths and deployment states.

## Layout and commands

- Shared Python code: `src/invest_assistant/`; install with `python -m pip install -e .`.
- Streamlit: `streamlit run apps/streamlit/app.py`. One page, six tabs; do not convert to multipage routing by moving tabs into `pages/`.
- React: `apps/web/`; `npm ci` then `npm run build`. Output remains `docs/` with `emptyOutDir: false` to preserve reports/data.
- Collection: `python -m invest_assistant.pipelines.collect update` (`init` and `sync` also supported).
- Recommendation/publication: `python -m invest_assistant.pipelines.recommend`.
- Backtest: `python -m invest_assistant.pipelines.backtest full-universe`.
- Tests: `python -m unittest discover -s tests -v`.
- Research: `python -m research.prediction_model.feature_engineering` and sibling modules.
- Docker: `docker compose -f infrastructure/docker-compose.yml up -d --build` from the root.
- Setup: `scripts/setup.bat`; research dependencies in `requirements-dev.txt`.

`paths.py` resolves `.env`, default OAuth file paths, public output and local artifacts relative to the checkout root.
Set `INVEST_ASSISTANT_HOME` for an installed deployment. `artifacts/` is local-only and ignored by Git.
Credentials, `.env`, local logs, notebooks and model artifacts must not be committed.

## Module responsibilities

`data/` fetches/validates prices and news; `universe.py` holds instrument metadata; `storage/` handles Drive and reports.
`analysis/` calculates signals/backtests; `recommendations/` produces ticker recommendations and LLM commentary;
`portfolio/` manages paper positions; `reporting/` builds HTML/Markdown/charts; `publishing/` exports JSON and Telegram;
`pipelines/` orchestrates collection and publication. Shared modules must not import Streamlit.
Streamlit widgets/session state stay in `apps/streamlit/tabs/`; caches in `services.py`; shared rendering in `components/`.

## Behavioral constraints

- Mechanical actions come only from `analysis.signals.get_mechanical_action`. LLM/news failures cannot downgrade a buy/sell to HOLD; use the rule-based explanation fallback.
- Preserve the Mr. Serenity system prompts; they explain long-term trend evidence and filter noise, without overriding action or suggested shares.
- Donchian windows are 20/100 days excluding today, ATR is Wilder 14, stop distance is 3 ATR, default position risk is 1%.
- Volume surge, Bollinger Bands and Ichimoku are advisory/display inputs, never gates for mechanical actions or position sizing.
- All 12 representative asset tickers use the same rules as individual stocks. Membership synchronization must exclude these proxies from S&P 500 delisting calculations.
- Validate OHLCV before saving/calculating. An incomplete representative-asset collection or recommendation batch must fail before publication.
- Preserve request throttling and cache keys tied to ticker/data freshness. Every Streamlit tab executes on each rerun.
- LLM/news inputs are required for their respective calls; preserve clear configuration errors and the caller's rule-based fallback.
- `SKIP_LLM_AND_NEWS` skips paid news/LLM in manual runs. `IS_TEST_REPORT` suffixes both recommendation and report filenames, without changing real signal history or static latest data.
- Test reports do have separate public HTML files. Telegram test behavior remains defined by the existing pipeline; tests must mock notifications.
- Historical `as_of` runs do not overwrite current JSON or send Telegram.
- Daily batch recommendation scope is representative assets. Individual S&P 500 mechanical signals remain available to React, but are omitted from report HTML and copied Markdown.
- Generate one portfolio overview in the recommendation pipeline and pass it to both HTML and static JSON; rendering/export modules must not call the LLM.
- Escape external LLM/news strings in HTML. Preserve Plotly HTML charts; do not reintroduce headless PNG rendering for Telegram.
- Paper-trading open/close operations are UI-only, never cron operations. Cron may read positions and returns.
- Backtest/model training are manual; the daily report only reads saved backtest summaries and does not display model predictions.
- Keep GitHub Pages `docs/data/` and `docs/reports/` paths and payload compatibility intact.

## Documentation

Archive the preceding current specification before updating its version. Keep historical snapshots unchanged.
Update current commands, workflow paths, architecture map and applicable guides together when moving code.
Verify with offline regression/integration tests and frontend builds before publishing changes.

"""Centralized configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

from invest_assistant.paths import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

# Google Drive "virtual DB" (OAuth user credentials — org policy blocks service account keys)
GOOGLE_OAUTH_CLIENT_SECRET_PATH = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", str(PROJECT_ROOT / "client_secret.json"))
GOOGLE_OAUTH_TOKEN_PATH = os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", str(PROJECT_ROOT / "token.json"))
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")


def _bootstrap_secret_file(path: str, env_var_name: str) -> None:
    """Headless environments (GitHub Actions, Streamlit Cloud) can't drop files into the repo,
    only inject secret values as env vars. If the file isn't already on disk but its content
    was provided via env var, write it out once so drive_db.py's file-path-based auth just works.
    """
    content = os.environ.get(env_var_name)
    if content and not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


_bootstrap_secret_file(GOOGLE_OAUTH_CLIENT_SECRET_PATH, "GOOGLE_OAUTH_CLIENT_SECRET_JSON")
_bootstrap_secret_file(GOOGLE_OAUTH_TOKEN_PATH, "GOOGLE_OAUTH_TOKEN_JSON")

# yfinance collection
INITIAL_HISTORY_PERIOD = os.environ.get("INITIAL_HISTORY_PERIOD", "5y")
YFINANCE_REQUEST_DELAY_SEC = float(os.environ.get("YFINANCE_REQUEST_DELAY_SEC", "0.5"))

# Trend-following signal engine (Tom Basso style)
DONCHIAN_ENTRY_WINDOW = int(os.environ.get("DONCHIAN_ENTRY_WINDOW", "20"))
DONCHIAN_LONG_WINDOW = int(os.environ.get("DONCHIAN_LONG_WINDOW", "100"))
ATR_WINDOW = int(os.environ.get("ATR_WINDOW", "14"))
ATR_STOP_MULTIPLIER = float(os.environ.get("ATR_STOP_MULTIPLIER", "3"))
DEFAULT_RISK_PCT = float(os.environ.get("DEFAULT_RISK_PCT", "0.01"))
VOLUME_SURGE_WINDOW = int(os.environ.get("VOLUME_SURGE_WINDOW", "20"))
VOLUME_SURGE_MULTIPLIER = float(os.environ.get("VOLUME_SURGE_MULTIPLIER", "1.5"))

# Bollinger Bands (chart-only reference indicator, not part of the Basso entry/exit rules)
BOLLINGER_WINDOW = int(os.environ.get("BOLLINGER_WINDOW", "20"))
BOLLINGER_NUM_STD = float(os.environ.get("BOLLINGER_NUM_STD", "2"))

# Ichimoku Kinko Hyo (chart-only reference overlay + advisory confluence note — never part
# of the Basso Donchian/ATR entry/exit rules or position sizing, see signal_engine.get_ichimoku_confluence)
ICHIMOKU_TENKAN_WINDOW = int(os.environ.get("ICHIMOKU_TENKAN_WINDOW", "9"))
ICHIMOKU_KIJUN_WINDOW = int(os.environ.get("ICHIMOKU_KIJUN_WINDOW", "26"))
ICHIMOKU_SENKOU_B_WINDOW = int(os.environ.get("ICHIMOKU_SENKOU_B_WINDOW", "52"))
ICHIMOKU_DISPLACEMENT = int(os.environ.get("ICHIMOKU_DISPLACEMENT", "26"))

# News collection (Exa search API — see https://exa.ai)
NEWS_MAX_ITEMS_PER_TICKER = int(os.environ.get("NEWS_MAX_ITEMS_PER_TICKER", "5"))
EXA_API_KEY = os.environ.get("EXA_API_KEY")
EXA_NEWS_LOOKBACK_DAYS = int(os.environ.get("EXA_NEWS_LOOKBACK_DAYS", "7"))

# General (non-ticker) macro/geopolitical news digest for the daily report's "오늘 챙겨야 할
# 해외 이슈" section (recommendation_engine.get_macro_issues_briefing) — a short lookback since
# this is meant to surface what's fresh today, not a week-old backlog like per-ticker news.
MACRO_NEWS_MAX_ITEMS = int(os.environ.get("MACRO_NEWS_MAX_ITEMS", "8"))
MACRO_NEWS_LOOKBACK_DAYS = int(os.environ.get("MACRO_NEWS_LOOKBACK_DAYS", "2"))

# LLM provider for the "Mr. Serenity" analysis (llm_briefing.py). OpenAI and OpenRouter both
# speak the same OpenAI-compatible /chat/completions contract (identical request body and
# `choices[0].message.content` response shape), so switching between them only changes the base
# URL, the API key and the model name — never any calling code. Set LLM_PROVIDER=openrouter to
# fall back to the previous free-tier setup, or point LLM_BASE_URL at any other compatible host.
# `or "openai"` rather than a get() default: GitHub Actions sets an unset `vars.LLM_PROVIDER`
# to an empty string, which a plain default wouldn't catch. Same reason for the `or`s below.
LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "openai").lower()

_LLM_PROVIDER_DEFAULTS = {
    # provider: (base URL, default model, conventional API-key env var name)
    "openai": ("https://api.openai.com/v1", "gpt-5", "OPENAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "nvidia/nemotron-3-ultra-550b-a55b:free", "OPENROUTER_API_KEY"),
}
if LLM_PROVIDER not in _LLM_PROVIDER_DEFAULTS:
    # Fail loudly at import rather than silently defaulting — a typo here would otherwise send
    # every LLM call to the wrong provider with the wrong key.
    raise ValueError(
        f"Unsupported LLM_PROVIDER={LLM_PROVIDER!r} (expected one of {sorted(_LLM_PROVIDER_DEFAULTS)})"
    )

_LLM_BASE_URL_DEFAULT, _LLM_MODEL_DEFAULT, _LLM_KEY_ENV = _LLM_PROVIDER_DEFAULTS[LLM_PROVIDER]

LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or _LLM_BASE_URL_DEFAULT
# Model IDs move faster than this file does — override via .env / Actions Secrets rather than
# editing the default above when a newer flagship model ships.
LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME") or _LLM_MODEL_DEFAULT
# Accept either the generic LLM_API_KEY or the provider's own conventional variable name, so an
# existing OPENROUTER_API_KEY keeps working unchanged when LLM_PROVIDER=openrouter.
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get(_LLM_KEY_ENV)
if LLM_PROVIDER == "openai" and not LLM_API_KEY:
    # Support the name used by the project's existing local .env.
    LLM_API_KEY = os.environ.get("OPENAI_KEY")

# Read timeout (seconds) for one /chat/completions call (llm_briefing._call_chat). Raised from
# the previously hardcoded 60s in v3.64: the "오늘 챙겨야 할 해외 이슈" briefing
# (generate_macro_issues_briefing) distills 8 articles into a 3-5 issue write-up in a single
# response, and gpt-5 repeatedly ran past 60s on it — it timed out in the 2026-09-09 cron run
# and again on the 2026-09-08 report rebuild, while the shorter calls in the same runs (per-
# ticker narrative, cross-asset overview) succeeded. A timeout here only loses that one
# optional section (every caller already falls back), so the cost of waiting longer is far
# lower than the cost of dropping it.
LLM_REQUEST_TIMEOUT_SEC = int(os.environ.get("LLM_REQUEST_TIMEOUT_SEC", "180"))

# Recommendation freshness gate — skip generating a 매수/HOLD/매도 call from stale data
# (e.g. a per-ticker fetch silently failed during collection). 4 days covers a normal
# weekend gap (Fri close -> Mon run) with one day of slack for a holiday.
DATA_FRESHNESS_MAX_AGE_DAYS = int(os.environ.get("DATA_FRESHNESS_MAX_AGE_DAYS", "4"))

# Telegram notifications for the daily asset-class recommendation run (cron only, not the
# interactive Streamlit UI). Bot token from @BotFather; chat_id from e.g. api.telegram.org/bot<token>/getUpdates.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Manual-test escape hatch (recommend.yml's workflow_dispatch input): skip the Exa news +
# LLM calls entirely and go straight to the rule-based explanation. For verifying
# the pipeline/report/Telegram plumbing without burning API quota on calls whose output isn't
# actually being checked. Never set for the real workflow_run-triggered (scheduled) path.
SKIP_LLM_AND_NEWS = os.environ.get("SKIP_LLM_AND_NEWS", "false").lower() == "true"

# Manual-test escape hatch (recommend.yml's workflow_dispatch input, default true there): when
# set, recommendation_engine.run_asset_class_recommendations appends "_test" to the report's
# filename (both Drive's _report_{date}.html and the local docs/reports/{date}.html) so a manual
# sample/test publish never overwrites that day's real scheduled report. Never set for the real
# workflow_run-triggered (scheduled) path, so production reports keep their plain date filename.
IS_TEST_REPORT = os.environ.get("IS_TEST_REPORT", "false").lower() == "true"

# Public GitHub Pages base URL where report_builder's daily HTML report is published
# (recommend.yml commits docs/reports/{date}.html, GitHub Pages serves the docs/ folder).
# telegram_notifier links here instead of attaching every ticker's chart individually.
REPORT_BASE_URL = os.environ.get("REPORT_BASE_URL", "https://garam827.github.io/ai_invest_assistant/reports")

# Streamlit UI-only toggle for public deployment (e.g. Streamlit Community Cloud): when false,
# app.py's chart tabs skip the LLM call (news collection still happens, gated behind
# an explicit button — see app.py) and fall back to a rule-based explanation instead. Defaults
# to true so local dev is unaffected; set to "false" via the deployed app's secrets/env. This is
# independent of SKIP_LLM_AND_NEWS above (that skips news too, and is cron-only).
STREAMLIT_ENABLE_LLM = os.environ.get("STREAMLIT_ENABLE_LLM", "true").lower() == "true"

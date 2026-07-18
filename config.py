"""Centralized configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Google Drive "virtual DB" (OAuth user credentials — org policy blocks service account keys)
GOOGLE_OAUTH_CLIENT_SECRET_PATH = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", "client_secret.json")
GOOGLE_OAUTH_TOKEN_PATH = os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", "token.json")
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

# News collection (Exa search API — see https://exa.ai)
NEWS_MAX_ITEMS_PER_TICKER = int(os.environ.get("NEWS_MAX_ITEMS_PER_TICKER", "5"))
EXA_API_KEY = os.environ.get("EXA_API_KEY")
EXA_NEWS_LOOKBACK_DAYS = int(os.environ.get("EXA_NEWS_LOOKBACK_DAYS", "7"))

# OpenRouter LLM ("Mr. Serenity" briefing)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL_NAME = os.environ.get("OPENROUTER_MODEL_NAME", "nvidia/nemotron-3-ultra-550b-a55b:free")

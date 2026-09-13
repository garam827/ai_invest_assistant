"""Read the same public files as React; no API clients, credentials, or writes."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from invest_assistant.paths import SITE_DIR


class SnapshotDB:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or SITE_DIR).resolve()

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid snapshot path")
        return path

    def _json(self, name: str, default):
        path = self._path(f"data/{name}.json")
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def validate(self) -> None:
        """Fail before serving an empty or incorrectly mounted deployment."""
        for name in ("universe", "signals_asset_class", "reports"):
            if not self._path(f"data/{name}.json").is_file():
                raise RuntimeError("Public data is missing. Mount the repository docs directory read-only.")
        if not self.list_tickers():
            raise RuntimeError("The public snapshot contains no tickers.")

    def generated_at(self) -> str:
        return self._json("signals_asset_class", {}).get("generated_at", "")

    def load_json(self, filename: str) -> dict | None:
        if filename == "_universe.json":
            items = self._json("universe", {}).get("sp500", [])
            return {
                "active_tickers": [item["ticker"] for item in items],
                "sectors": {item["ticker"]: item.get("sector", "") for item in items},
                "descriptions": {item["ticker"]: item.get("description", "") for item in items},
            }
        if filename == "_signal_history.json":
            return {item["date"]: item.get("actions", {}) for item in self._json("reports", {}).get("dates", [])}
        return None

    def list_tickers(self) -> list[str]:
        data = self._json("universe", {})
        return sorted({item["ticker"] for group in ("asset_classes", "sp500") for item in data.get(group, [])})

    def load_ticker(self, ticker: str) -> pd.DataFrame | None:
        if not re.fullmatch(r"[A-Za-z0-9.^=-]{1,24}", ticker) or ticker not in self.list_tickers():
            raise ValueError("Unknown public ticker")
        path = self._path(f"data/charts/{ticker}.json")
        if not path.is_file():
            return None
        frame = pd.read_json(path)
        if not frame.empty:
            frame["Date"] = pd.to_datetime(frame["Date"])
        return frame

    def recommendation(self, ticker: str) -> dict | None:
        for item in self._json("signals_asset_class", {}).get("tickers", []):
            if item.get("ticker") == ticker:
                return item
        return None

    def list_filenames(self, prefix: str) -> list[str]:
        if prefix != "_report_":
            return []
        dates = self._json("reports", {}).get("dates", [])
        return [f"_report_{item['date']}.html" for item in dates
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["date"])]

    def load_text(self, filename: str) -> str | None:
        if filename not in self.list_filenames("_report_"):
            return None
        path = self._path(f"reports/{filename.removeprefix('_report_')}")
        return path.read_text(encoding="utf-8") if path.is_file() else None

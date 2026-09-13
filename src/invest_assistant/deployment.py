"""Validate the public mount and run Streamlit (no cloud provisioning)."""
from __future__ import annotations

import argparse
import os
import sys

from invest_assistant import config
from invest_assistant.paths import PROJECT_ROOT
from invest_assistant.storage.snapshot import SnapshotDB


def preflight() -> None:
    if not config.STREAMLIT_PUBLIC_MODE:
        raise RuntimeError("Deployment entry point requires STREAMLIT_PUBLIC_MODE=true.")
    SnapshotDB().validate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate local public files without starting a server")
    args = parser.parse_args()
    preflight()
    if args.check:
        print("Public snapshot ready; external credentials and API calls are not required.")
        return
    port = int(os.environ.get("PORT", "8501"))
    if not 1024 <= port <= 65535:
        raise ValueError("PORT must be between 1024 and 65535")
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run", str(PROJECT_ROOT / "apps/streamlit/app.py"),
        f"--server.port={port}", "--server.address=0.0.0.0", "--server.headless=true",
        "--browser.gatherUsageStats=false", "--server.fileWatcherType=none",
        "--client.showErrorDetails=false",
    ])


if __name__ == "__main__":
    main()

"""Runtime paths independent of the shell's current directory.

INVEST_ASSISTANT_HOME overrides the checkout root for installed deployments.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("INVEST_ASSISTANT_HOME", Path(__file__).resolve().parents[2])).resolve()
SITE_DIR = PROJECT_ROOT / "docs"
REPORT_DIR = SITE_DIR / "reports"
ARTIFACT_DIR = PROJECT_ROOT / "artifacts"

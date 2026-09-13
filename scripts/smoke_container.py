"""Local/CI Docker smoke test; no domain, credentials, Tunnel, or GCP resources."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    env = {**os.environ, "STREAMLIT_LOCAL_PORT": os.environ.get("STREAMLIT_LOCAL_PORT", "18501")}
    compose = ["docker", "compose", "--project-name", "ai-invest-smoke",
               "-f", "infrastructure/docker-compose.yml", "-f", "infrastructure/docker-compose.local.yml"]

    def run(*arguments, timeout=120):
        subprocess.run([*compose, *arguments], cwd=ROOT, env=env, check=True, timeout=timeout)

    def wait_ready():
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{env['STREAMLIT_LOCAL_PORT']}/_stcore/health", timeout=3) as response:
                    if response.status == 200 and response.read() == b"ok":
                        return
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(1)
        raise RuntimeError("Container health endpoint did not become ready")

    try:
        run("up", "-d", "--build", timeout=900)
        wait_ready()
        run("exec", "-T", "streamlit-app", "python", "-c",
            "import os; from pathlib import Path; from invest_assistant import config; "
            "from invest_assistant.storage.snapshot import SnapshotDB; "
            "assert os.getuid() == 10001; assert config.STREAMLIT_PUBLIC_MODE; "
            "assert not config.EXA_API_KEY and not config.LLM_API_KEY; "
            "assert not Path(config.GOOGLE_OAUTH_TOKEN_PATH).exists(); "
            "SnapshotDB().validate(); assert SnapshotDB().load_ticker('SPY') is not None; "
            "print('Non-root public snapshot is ready without credentials.')")
        run("exec", "-T", "streamlit-app", "python", "-m", "unittest", "discover", "-s", "tests",
            "-p", "test_deployment.py", "-k", "PublicDeploymentTests", "-v")
        run("restart", "streamlit-app")
        wait_ready()
        print("Container health, mounted data, offline public UI, and restart verified.")
    finally:
        run("down", "--remove-orphans")


if __name__ == "__main__":
    main()

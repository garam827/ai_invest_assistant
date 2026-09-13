"""Explicit, local-only OAuth consent setup. Never run as the web entry point."""
import os

os.environ["GOOGLE_OAUTH_ALLOW_INTERACTIVE"] = "true"

from invest_assistant.storage.drive import _load_credentials  # noqa: E402

if __name__ == "__main__":
    _load_credentials()
    print("Drive authorization saved. Keep the token file outside version control.")

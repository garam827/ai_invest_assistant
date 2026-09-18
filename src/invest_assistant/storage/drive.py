"""Google Drive-backed "virtual DB": one Parquet file per ticker in a single Drive folder.

Auth is via OAuth user credentials, not a service account key — some GCP orgs enforce
the iam.disableServiceAccountKeyCreation policy, which blocks service account keys outright.
Run scripts/authorize_drive.py locally for explicit browser consent. Headless processes
refresh an existing token and never initiate consent by default. Public deployments
do not use Drive credentials.
"""
from __future__ import annotations

import io
import json
import logging
import os

import pandas as pd
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from invest_assistant import config
from invest_assistant.data.quality import validate_ohlcv
from invest_assistant.storage.runtime import (
    atomic_write_private,
    credential_serialized,
    require_private_operation,
    serialized,
    ticker_transaction,
    transport_serialized,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
PARQUET_MIMETYPE = "application/octet-stream"


class _SerializedCredentials(Credentials):
    """Protect refreshes triggered automatically by each worker's transport."""

    @credential_serialized
    def refresh(self, request):
        require_private_operation()
        try:
            super().refresh(request)
        except RefreshError:
            raise RuntimeError("Drive authorization must be renewed on a trusted local machine.") from None
        atomic_write_private(config.GOOGLE_OAUTH_TOKEN_PATH, self.to_json())


@credential_serialized
def _load_credentials() -> Credentials:
    """Load cached OAuth credentials, refreshing or running the consent flow as needed."""
    require_private_operation()
    creds = None
    token_path = config.GOOGLE_OAUTH_TOKEN_PATH
    if os.path.exists(token_path):
        creds = _SerializedCredentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                raise RuntimeError("Drive authorization must be renewed on a trusted local machine.") from None
        else:
            if not config.GOOGLE_OAUTH_ALLOW_INTERACTIVE:
                raise RuntimeError("Drive token missing or invalid. Run scripts/authorize_drive.py locally first.")
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GOOGLE_OAUTH_CLIENT_SECRET_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)
            creds = _SerializedCredentials.from_authorized_user_info(json.loads(creds.to_json()), SCOPES)
        atomic_write_private(token_path, creds.to_json())

    return creds


class DriveDB:
    """Reads/writes per-ticker OHLCV Parquet files inside one Drive folder."""

    @serialized
    def __init__(self, folder_id: str | None = None):
        require_private_operation()
        self.folder_id = folder_id or config.DRIVE_FOLDER_ID
        if not self.folder_id:
            raise ValueError("DRIVE_FOLDER_ID is not set (env var or constructor arg)")

        credentials = _load_credentials()
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _filename(ticker: str) -> str:
        return f"{ticker}.parquet"

    def new_worker(self) -> DriveDB:
        """Build an independent HTTP client in the calling worker thread."""
        return DriveDB(folder_id=self.folder_id)

    @transport_serialized
    def close(self) -> None:
        self.service.close()

    def _find_file_id(self, filename: str) -> str | None:
        query = f"name = '{filename}' and '{self.folder_id}' in parents and trashed = false"
        response = (
            self.service.files()
            .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None

    @transport_serialized
    def list_tickers(self) -> list[str]:
        """List all tickers currently stored in the Drive folder."""
        tickers: list[str] = []
        page_token = None
        query = f"'{self.folder_id}' in parents and trashed = false and name contains '.parquet'"
        while True:
            response = (
                self.service.files()
                .list(q=query, spaces="drive", fields="nextPageToken, files(name)", pageToken=page_token)
                .execute()
            )
            tickers.extend(f["name"].removesuffix(".parquet") for f in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return tickers

    @transport_serialized
    def _download(self, filename: str) -> bytes | None:
        file_id = self._find_file_id(filename)
        if file_id is None:
            return None

        buffer = io.BytesIO()
        request = self.service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    @transport_serialized
    def _upload(self, filename: str, data: bytes, mimetype: str) -> None:
        require_private_operation()
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype, resumable=False)
        file_id = self._find_file_id(filename)
        if file_id is None:
            metadata = {"name": filename, "parents": [self.folder_id]}
            self.service.files().create(body=metadata, media_body=media, fields="id").execute()
        else:
            self.service.files().update(fileId=file_id, media_body=media).execute()

    def load_ticker(self, ticker: str) -> pd.DataFrame | None:
        """Download and parse a ticker's Parquet file. Returns None if it doesn't exist yet."""
        raw = self._download(self._filename(ticker))
        if raw is None:
            return None
        return pd.read_parquet(io.BytesIO(raw))

    @ticker_transaction
    def save_ticker(self, ticker: str, df: pd.DataFrame) -> None:
        """Overwrite (or create) a ticker's Parquet file with the given DataFrame."""
        validate_ohlcv(df)
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        self._upload(self._filename(ticker), buffer.getvalue(), PARQUET_MIMETYPE)

    def load_json(self, filename: str) -> dict | None:
        """Download and parse a small JSON metadata file (e.g. the ticker universe). None if missing."""
        raw = self._download(filename)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    def save_json(self, filename: str, data: dict) -> None:
        """Overwrite (or create) a small JSON metadata file."""
        self._upload(filename, json.dumps(data, indent=2).encode("utf-8"), "application/json")

    def load_text(self, filename: str) -> str | None:
        """Download a plain-text/HTML file (e.g. a daily report page). None if missing."""
        raw = self._download(filename)
        return raw.decode("utf-8") if raw is not None else None

    def save_text(self, filename: str, text: str, mimetype: str = "text/html") -> None:
        """Overwrite (or create) a plain-text/HTML file."""
        self._upload(filename, text.encode("utf-8"), mimetype)

    @transport_serialized
    def list_filenames(self, prefix: str) -> list[str]:
        """List filenames in the Drive folder starting with `prefix` (e.g. '_report_')."""
        filenames: list[str] = []
        page_token = None
        query = f"'{self.folder_id}' in parents and trashed = false and name contains '{prefix}'"
        while True:
            response = (
                self.service.files()
                .list(q=query, spaces="drive", fields="nextPageToken, files(name)", pageToken=page_token)
                .execute()
            )
            filenames.extend(f["name"] for f in response.get("files", []) if f["name"].startswith(prefix))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return sorted(filenames)

    @ticker_transaction
    def upsert_ticker(self, ticker: str, new_df: pd.DataFrame) -> pd.DataFrame:
        """Merge new rows into the existing file, drop duplicate dates (keep newest), save, return merged df."""
        existing_df = self.load_ticker(ticker)
        if existing_df is not None and not existing_df.empty:
            merged = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            merged = new_df

        merged = (
            merged.drop_duplicates(subset="Date", keep="last")
            .sort_values("Date")
            .reset_index(drop=True)
        )
        self.save_ticker(ticker, merged)
        return merged

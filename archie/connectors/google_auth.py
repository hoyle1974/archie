"""Google OAuth for the read-only Google connectors and the Gemini usage check (monitoring).
Tokens live in the macOS Keychain (via keyring), never under ~/.archie or the repo."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from archie.secrets import get_secret, set_secret

TOKEN_KEY = "google-token"
CLIENT_KEY = "google-client"

SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "calendar": "https://www.googleapis.com/auth/calendar.readonly",
    "drive": "https://www.googleapis.com/auth/drive.readonly",
    "monitoring": "https://www.googleapis.com/auth/monitoring.read",
}


_REFRESH = threading.Lock()


class NeedsAuth(RuntimeError):
    pass


def _save(creds) -> None:
    set_secret(TOKEN_KEY, creds.to_json())


def granted_scopes() -> set[str]:
    raw = get_secret(TOKEN_KEY)
    return set(json.loads(raw).get("scopes") or []) if raw else set()


def credentials(source: str):
    """Credentials that include the scope for `source`, refreshed if expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    raw = get_secret(TOKEN_KEY)
    if not raw:
        raise NeedsAuth("Google isn't connected yet: run `archie admin connect google`")
    info = json.loads(raw)
    if SCOPES[source] not in (info.get("scopes") or []):
        raise NeedsAuth(f"Google access doesn't include {source}: run `archie admin connect google` again")
    with _REFRESH:  # connectors sync in parallel and share one token: refresh it once
        raw = get_secret(TOKEN_KEY) or raw  # another connector may have just refreshed it
        creds = Credentials.from_authorized_user_info(json.loads(raw))
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            try:
                _save(creds)
            except Exception as exc:  # the fresh token still works for this sync; save it next time
                import logging

                logging.getLogger(__name__).warning("couldn't save the refreshed Google token: %s", exc)
    return creds


def service(api: str, version: str, source: str):
    from googleapiclient.discovery import build

    return build(api, version, credentials=credentials(source), cache_discovery=False)


def connect(client_file: Path | None = None, sources: tuple[str, ...] = ("gmail", "calendar", "drive")) -> set[str]:
    """Run the browser consent flow for read-only access; stores client and token in the Keychain."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if client_file:
        set_secret(CLIENT_KEY, Path(client_file).read_text())
    client = get_secret(CLIENT_KEY)
    if not client:
        raise NeedsAuth("no Google OAuth client yet: pass --client <client.json> (a Desktop OAuth client)")
    flow = InstalledAppFlow.from_client_config(json.loads(client), [SCOPES[s] for s in sources])
    creds = flow.run_local_server(port=0, open_browser=True)
    _save(creds)
    return set(creds.scopes or [])


def import_token(token_file: Path) -> set[str]:
    """Adopt an existing authorized-user token file (e.g. v0's read-only Gmail token)."""
    info = json.loads(Path(token_file).read_text())
    set_secret(TOKEN_KEY, json.dumps(info))
    return set(info.get("scopes") or [])

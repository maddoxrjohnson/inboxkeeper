"""OAuth for Gmail using the user's own Google Cloud "Desktop app" client.

Each user brings their own client ID (see docs/setup-gmail.md). That keeps the
app out of Google's restricted-scope verification process and means no shared
secret ever ships with the code.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

log = logging.getLogger(__name__)

# gmail.modify can read, label and trash mail but cannot permanently delete
# it. That limit is deliberate: the worst this app can do is recoverable.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

REVOKE_URL = "https://oauth2.googleapis.com/revoke"
PENDING_FLOW_TTL = 10 * 60

# Users can untick scopes on Google's consent screen. Let the token exchange
# succeed so we can show a useful message instead of oauthlib's warning.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class AuthError(Exception):
    pass


class GoogleAuth:
    def __init__(self, data_dir: Path) -> None:
        self.client_secrets_path = data_dir / "credentials.json"
        self.token_path = data_dir / "token.json"
        self._pending: dict[str, tuple[Flow, float]] = {}

    def has_client_secrets(self) -> bool:
        return self.client_secrets_path.is_file()

    def has_token(self) -> bool:
        return self.token_path.is_file()

    def start(self, redirect_uri: str) -> str:
        """Begin the consent flow and return the URL to send the user to."""
        flow = Flow.from_client_config(
            self._client_config(), scopes=SCOPES, redirect_uri=redirect_uri
        )
        url, state = flow.authorization_url(access_type="offline", prompt="consent")
        self._prune_pending()
        self._pending[state] = (flow, time.monotonic())
        return str(url)

    def finish(self, state: str, code: str) -> Credentials:
        entry = self._pending.pop(state, None)
        if entry is None:
            raise AuthError("This sign-in link has expired. Please try connecting again.")

        flow, _ = entry
        flow.fetch_token(code=code)
        creds: Credentials = flow.credentials

        granted = creds.granted_scopes or []
        if isinstance(granted, str):
            granted = granted.split()
        if not set(SCOPES) <= set(granted):
            raise AuthError(
                "Google didn't grant permission to manage your mail. Reconnect and "
                "leave the Gmail checkbox ticked on the consent screen."
            )

        self._save(creds)
        return creds

    def load_credentials(self) -> Credentials | None:
        """Return valid credentials, refreshing them if needed, or None."""
        if not self.has_token():
            return None
        try:
            creds = Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
                json.loads(self.token_path.read_text()), SCOPES
            )
        except (ValueError, KeyError) as exc:
            log.warning("stored token is unreadable, discarding it: %s", exc)
            self.token_path.unlink(missing_ok=True)
            return None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                # Usually a revoked grant, or the 7-day expiry Google applies
                # to apps still in "Testing" mode.
                log.info("token refresh failed, user must reconnect: %s", exc)
                self.token_path.unlink(missing_ok=True)
                return None
            self._save(creds)

        return creds if creds.valid else None

    def disconnect(self) -> None:
        if self.has_token():
            try:
                token = json.loads(self.token_path.read_text()).get("refresh_token")
                if token:
                    requests.post(REVOKE_URL, params={"token": token}, timeout=10)
            except (OSError, ValueError, requests.RequestException) as exc:
                log.warning("couldn't revoke token with Google: %s", exc)
        self.token_path.unlink(missing_ok=True)

    def _client_config(self) -> dict[str, Any]:
        if not self.has_client_secrets():
            raise AuthError(f"No OAuth client found at {self.client_secrets_path}.")
        try:
            config: dict[str, Any] = json.loads(self.client_secrets_path.read_text())
        except ValueError as exc:
            raise AuthError(f"{self.client_secrets_path} isn't valid JSON.") from exc
        if "installed" not in config:
            raise AuthError(
                'The OAuth client must be of type "Desktop app". Create a new client '
                "ID of that type and download its JSON again."
            )
        return config

    def _save(self, creds: Credentials) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        # Owner-only permissions: this file grants access to the mailbox.
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(creds.to_json())  # type: ignore[no-untyped-call]

    def _prune_pending(self) -> None:
        cutoff = time.monotonic() - PENDING_FLOW_TTL
        self._pending = {s: e for s, e in self._pending.items() if e[1] > cutoff}

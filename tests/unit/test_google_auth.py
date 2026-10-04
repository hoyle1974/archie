"""Google token refresh: connectors share one token, and a failed Keychain save doesn't
fail the sync (2026-10-04: calendar failed with "Can't store password on keychain")."""

import json
import threading

from archie.connectors import google_auth


class FakeCreds:
    refreshed = 0

    def __init__(self, info):
        self.info = info
        self.valid = info.get("fresh", False)
        self.refresh_token = "r"

    def refresh(self, request):
        FakeCreds.refreshed += 1
        self.info = {**self.info, "fresh": True}
        self.valid = True

    def to_json(self):
        return json.dumps(self.info)

    @classmethod
    def from_authorized_user_info(cls, info):
        return cls(info)


def test_a_keychain_save_failure_still_returns_working_credentials(monkeypatch):
    import google.oauth2.credentials as gcreds

    store = {"google-token": json.dumps({"scopes": [google_auth.SCOPES["calendar"]]})}
    monkeypatch.setattr(google_auth, "get_secret", lambda k: store.get(k))

    def save(key, value):
        raise RuntimeError("Can't store password on keychain: (-67701, 'Unknown Error')")

    monkeypatch.setattr(google_auth, "set_secret", save)
    monkeypatch.setattr(gcreds, "Credentials", FakeCreds)
    assert google_auth.credentials("calendar").valid


def test_parallel_connectors_refresh_the_shared_token_once(monkeypatch):
    import google.oauth2.credentials as gcreds

    scopes = [google_auth.SCOPES["calendar"], google_auth.SCOPES["gmail"]]
    store = {"google-token": json.dumps({"scopes": scopes})}
    monkeypatch.setattr(google_auth, "get_secret", lambda k: store.get(k))
    monkeypatch.setattr(google_auth, "set_secret", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(gcreds, "Credentials", FakeCreds)
    FakeCreds.refreshed = 0
    threads = [threading.Thread(target=google_auth.credentials, args=(s,)) for s in ("calendar", "gmail")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert FakeCreds.refreshed == 1

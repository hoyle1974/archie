import time

import pytest

from archie import secrets


def test_blocked_keychain_read_explains_itself(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda s, k: time.sleep(5))
    with pytest.raises(secrets.KeychainWaiting, match="Always Allow"):
        secrets.get_secret("google-token", timeout=0.1)


def test_normal_read(monkeypatch):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda s, k: f"{s}:{k}")
    assert secrets.get_secret("x") == "archie:x"

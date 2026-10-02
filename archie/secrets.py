"""Keychain access (via keyring) that never hangs silently.

macOS asks before a program it doesn't yet trust can read a Keychain item. That dialog
blocks the read with no sign in the terminal, so reads time out with an explanation."""

from __future__ import annotations

import threading

SERVICE = "archie"
TIMEOUT = 15.0


class KeychainWaiting(RuntimeError):
    pass


def get_secret(key: str, timeout: float = TIMEOUT) -> str | None:
    import keyring

    box: dict = {}

    def read():
        try:
            box["value"] = keyring.get_password(SERVICE, key)
        except Exception as exc:  # surface keyring errors to the caller
            box["error"] = exc

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise KeychainWaiting(f"waiting for Keychain permission to read '{key}': look for a macOS dialog "
                              "and choose Always Allow")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def set_secret(key: str, value: str) -> None:
    import keyring

    keyring.set_password(SERVICE, key, value)

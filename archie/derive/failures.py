"""Stop retrying items whose model call keeps failing because of the item itself.

Derivers leave an item unprocessed when its model call fails, so the next sync retries it.
For a service problem (quota, network, key) that's right. For a failure caused by the input
(an unreadable or cut-off reply, a safety block) it would cost a call every sync forever, so
after MAX_TRIES such failures on the same content the item is skipped. New content (a new
message in the thread) gets a fresh start. The record is `state/llm_failures.yaml`; deleting
an entry (or the file) retries it.
"""

from __future__ import annotations

import threading

import yaml

from archie.llm.backend import LLMError
from archie.store.files import atomic_write
from archie.store.home import Home

MAX_TRIES = 3
FILE = "state/llm_failures.yaml"


class Failures:
    def __init__(self, home: Home):
        self.path = home.root / FILE
        self.items: dict[str, dict] = (yaml.safe_load(self.path.read_text()) or {}) if self.path.exists() else {}
        self.changed = False
        self.lock = threading.Lock()

    def gave_up(self, key: str, version: str) -> bool:
        with self.lock:
            item = self.items.get(key)
            return bool(item) and item.get("version") == version and item.get("tries", 0) >= MAX_TRIES

    def failed(self, key: str, version: str, exc: LLMError) -> None:
        if not exc.about_input:
            return
        with self.lock:
            item = self.items.get(key)
            tries = item["tries"] + 1 if item and item.get("version") == version else 1
            self.items[key] = {"version": version, "tries": tries, "error": str(exc)[:200]}
            self.changed = True

    def ok(self, key: str) -> None:
        with self.lock:
            if self.items.pop(key, None) is not None:
                self.changed = True

    def skipped(self) -> list[str]:
        return sorted(k for k, v in self.items.items() if v.get("tries", 0) >= MAX_TRIES)

    def save(self) -> None:
        if self.changed:
            atomic_write(self.path, yaml.safe_dump(self.items, sort_keys=True))
            self.changed = False

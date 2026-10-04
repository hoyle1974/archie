"""Conversation memory for `ask` (state/conversation.jsonl). Each finished exchange keeps the
user's words, the question as understood, the answer's summary and its numbered citations.
Follow-ups ("show 1", "really?", "them") read the recent ones."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from archie.store.files import atomic_write
from archie.store.home import Home

FILE = "state/conversation.jsonl"
KEEP = 200
RECENT = 3
WINDOW = timedelta(minutes=30)


def load(home: Home) -> list[dict]:
    path = home / FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and "ts" in item:
            out.append(item)
    return out


def append(home: Home, entry: dict) -> None:
    entries = (load(home) + [entry])[-KEEP:]
    atomic_write(home / FILE, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))


def _when(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def recent(home: Home, now: datetime) -> list[dict]:
    """The last few exchanges, oldest first. A gap of more than 30 minutes (between two
    exchanges, or since the newest) ends the conversation, so an old topic isn't pulled in."""
    out: list[dict] = []
    later = now
    for entry in reversed(load(home)):
        when = _when(entry)
        if when is None or later - when > WINDOW or len(out) == RECENT:
            break
        out.append(entry)
        later = when
    return list(reversed(out))

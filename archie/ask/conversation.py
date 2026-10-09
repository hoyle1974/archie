"""Conversation memory for `ask` (state/conversation.jsonl). Each finished exchange keeps the
user's words, the question as understood, the answer's summary, its numbered citations and
the answer as shown (`shown`, with any Markdown part of it in `markdown`). Follow-ups ("really?",
"them") read the recent ones; "show 1" reads the newest, however old, because the TUI shows the
last few again on launch."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from archie.store.files import atomic_write
from archie.store.home import Home
from archie.store.times import stamp

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


def shown(entry: dict) -> str:
    """The answer as it was shown. Exchanges saved before `shown` existed give when they were
    asked and the summary."""
    if entry.get("shown"):
        return entry["shown"]
    when = _when(entry)
    summary = entry.get("summary") or ""
    return f"{stamp(when)}\n\n{summary}" if when else summary


def latest(home: Home) -> dict | None:
    """The newest exchange, however old: the answer on screen that "show N" opens."""
    entries = load(home)
    return entries[-1] if entries else None


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

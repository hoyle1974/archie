"""Briefing timing (DESIGN §7.3): build today's briefings in a morning batch, rebuild at
T-`lead_minutes` if their inputs changed, and notify once per meeting."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from typing import Callable

from archie.ask.context import Ctx
from archie.briefings.build import _path, build_briefing, upcoming
from archie.store.files import read_note, write_note

Notify = Callable[[str, str], None]


def mac_notify(title: str, message: str) -> None:
    script = f'display notification {message!r} with title "Archie" subtitle {title!r}'
    subprocess.run(["osascript", "-e", script.replace("'", '"')], capture_output=True, timeout=10)


def todays(ctx: Ctx):
    today = ctx.now.astimezone().date()
    return [m for m in upcoming(ctx, hours=24) if datetime.fromisoformat(m.meta["start"]).astimezone().date() == today]


def tick(ctx: Ctx, notify: Notify = mac_notify) -> list[str]:
    """Run every minute. Returns titles of briefings (re)built this tick."""
    built = []
    lead = timedelta(minutes=ctx.config["briefings"]["lead_minutes"])
    for m in todays(ctx):
        path = ctx.home / _path(m)
        start = datetime.fromisoformat(m.meta["start"])
        due = start - lead <= ctx.now
        if path.exists() and not due:
            continue
        b = build_briefing(ctx, m)
        if not b.reused:
            built.append(m.meta.get("title"))
        if due:
            note = read_note(path)
            if not note.meta.get("notified"):
                notify(m.meta.get("title") or "Meeting", f"Starts at {start.astimezone():%-I:%M %p}. Briefing ready.")
                note.meta["notified"] = True
                write_note(path, note)
    return built

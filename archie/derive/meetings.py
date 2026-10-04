"""Meetings: one note per timed calendar occurrence (DESIGN §4.3). Occurrences with other
people are meetings (typed, briefed); ones without are personal events (type "event"):
they appear in Today's agenda and count as busy time, but get no briefing.

meetings/<YYYY>/<YYYY-MM-DD>-<slug>.md, found again by `event_id` so a renamed event
keeps its file. Archie owns the frontmatter keys below and the fence; `## My notes` and
everything else outside the fence is the user's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from archie.ask.context import Ctx
from archie.briefings.classify import classify, load_overrides
from archie.derive.people import PeopleDirectory, Seen, slug, upsert_person
from archie.store.fence import set_fence
from archie.store.files import Note, read_note, read_raw, write_note
from archie.store.home import Home
from archie.store.times import utc_iso

OWNED = ("event_id", "series_id", "title", "start", "end", "type", "attendees", "attendee_names", "linked_docs",
         "status", "link")


@dataclass
class Meeting:
    rel_path: str
    note: Note

    @property
    def meta(self) -> dict:
        return self.note.meta


def load_meetings(home: Home) -> list[Meeting]:
    return [Meeting(p.relative_to(home.root).as_posix(), read_note(p)) for p in sorted((home / "meetings").rglob("*.md"))]


def find_meeting(home: Home, event_id: str) -> Meeting | None:
    return next((m for m in load_meetings(home) if m.meta.get("event_id") == event_id), None)


def others(data: dict, me) -> list[dict]:
    return [a for a in data.get("attendees", []) if not a.get("self") and not me.is_me(a.get("email", ""))]


def derive_meetings(ctx: Ctx, paths: list[Path]) -> None:
    by_event = {m.meta.get("event_id"): m for m in load_meetings(ctx.home)}
    directory = PeopleDirectory.load(ctx.home)
    overrides = load_overrides(ctx.home)
    now = ctx.now.isoformat()
    for path in sorted(paths):
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        if not rel.startswith("sources/calendar/") or not Path(path).exists():
            continue
        data = read_raw(path)
        existing = by_event.get(data.get("id"))
        if data.get("deleted"):
            if existing and existing.meta.get("status") != "cancelled":
                existing.meta["status"] = "cancelled"
                write_note(ctx.home / existing.rel_path, existing.note)
            continue
        people = others(data, ctx.me)
        if data.get("all_day"):
            continue
        ids = []
        for a in people:
            if utc_iso(data["start"]) <= now:  # a meeting that happened counts as an interaction
                seen = Seen()
                seen.at(data["start"], a.get("name", ""))
            else:  # an invite to a future meeting only introduces the person
                seen = Seen(names={a.get("name", "")} - {""}, first=now, last="")
            ids.append(upsert_person(ctx.home, directory, a["email"], seen, via="calendar"))
        meta = {"event_id": data["id"], "series_id": data.get("series_id"), "title": data.get("title"),
                "start": utc_iso(data["start"]), "end": utc_iso(data["end"]),
                "type": classify(data, ctx.config, overrides) if people else "event",
                "attendees": ids, "attendee_names": [directory.name(i) for i in ids],
                "linked_docs": [a["file_id"] for a in data.get("attachments", []) if a.get("file_id")],
                "status": "declined" if any(a.get("self") and a.get("response") == "declined"
                                            for a in data.get("attendees", [])) else "scheduled",
                "link": data.get("link", "")}
        if existing:
            note = existing.note
            meta["type_auto"] = meta["type"]  # what Archie would choose
            if note.meta.get("type") != note.meta.get("type_auto", note.meta.get("type")):
                meta["type"] = note.meta["type"]  # the user changed it in the file: their value wins
            note.meta.update(meta)
            rel_note = existing.rel_path
        else:
            when = datetime.fromisoformat(data["start"]).astimezone()
            rel_note = f"meetings/{when:%Y}/{when:%Y-%m-%d}-{slug(data.get('title') or 'meeting')[:40].replace('_', '-')}.md"
            n = 2
            while (ctx.home / rel_note).exists():
                rel_note = rel_note.replace(".md", f"-{n}.md") if n == 2 else rel_note.replace(f"-{n - 1}.md", f"-{n}.md")
                n += 1
            meta["type_auto"] = meta["type"]
            note = Note(meta=meta, body="## My notes\n\n")
            note.body = set_fence(note.body, "## Decisions\n\n## Action items\n")
        write_note(ctx.home / rel_note, note)
        by_event[data["id"]] = Meeting(rel_note, note)

def recent_or_upcoming(ctx: Ctx, text: str | None, back_hours: int = 24 * 7, ahead_hours: int = 24 * 7) -> Meeting | None:
    if not text:
        return None
    lo, hi = ctx.now - timedelta(hours=back_hours), ctx.now + timedelta(hours=ahead_hours)
    words = set(re.findall(r"\w+", text.lower())) - {"the", "my", "meeting", "with", "from", "notes", "a", "is"}
    best, best_score = None, 0
    for m in load_meetings(ctx.home):
        start = datetime.fromisoformat(m.meta["start"])
        if not lo <= start <= hi:
            continue
        score = len(words & set(re.findall(r"\w+", (m.meta.get("title") or "").lower())))
        if score > best_score or (score == best_score and best and abs(start - ctx.now) < abs(
                datetime.fromisoformat(best.meta["start"]) - ctx.now)):
            best, best_score = m, score
    return best if best_score else None

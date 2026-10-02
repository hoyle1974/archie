"""Build a meeting briefing (DESIGN §7): retrieval in code by meeting type, a cited summary
from the LLM, and code-computed People and Open sections. Saved to briefings/ and reused
while its inputs are unchanged."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.render import render
from archie.ask.synthesize import synthesize
from archie.derive.loops import load_loops, rank
from archie.derive.meetings import Meeting, load_meetings
from archie.derive.people import PeopleDirectory, slug
from archie.index.chunk import short_date
from archie.index.search import search
from archie.llm.verify import Packet
from archie.store.files import Note, read_note, write_note

INSTRUCTIONS = {
    "standard": """- This is a briefing {me_name} reads minutes before a meeting. Summary: what the meeting
  is about and the one or two things {me_name} most needs to know or do.
- Optional sections: "What changed" (recent developments relevant to this meeting) and
  conflicts between sources ("⚠️ Conflict: …", citing both sides).""",
    "one_on_one": """- This is a briefing for a recurring 1:1. Summary: what changed since the last 1:1 and
  what is still open between them.
- Optional sections: "Since last time" (their progress, what they shipped or said),
  "Topics to raise", and conflicts between sources ("⚠️ Conflict: …").""",
    "standup": """- This is a standup briefing. Use sections "Yesterday" (what {me_name} did, from their own
  messages and notes), "Today" (what they said they'd do next), and "Blockers".
  Summary: one sentence.""",
    "all_hands": """- This is an all-hands. Summary: the likely company-level topics, from announcements and
  docs. Skip individual tickets and peer-level detail.""",
}


@dataclass
class Briefing:
    meeting: Meeting
    answer: Answer
    path: str
    reused: bool = False


def _start(m: Meeting) -> datetime:
    return datetime.fromisoformat(m.meta["start"])


def upcoming(ctx: Ctx, hours: int = 36) -> list[Meeting]:
    horizon = ctx.now + timedelta(hours=hours)
    out = [m for m in load_meetings(ctx.home) if m.meta.get("status") == "scheduled"
           and datetime.fromisoformat(m.meta["end"]) > ctx.now and _start(m) < horizon]
    return sorted(out, key=_start)


def pick_meeting(ctx: Ctx, text: str | None) -> Meeting | None:
    cands = upcoming(ctx)
    if not cands:
        return None
    q = (text or "").strip().lower()
    if not q or q in ("next", "my next meeting", "next meeting", "upcoming"):
        return cands[0]
    t = re.search(r"\b(\d{1,2})(?::(\d\d))?\s*(am|pm)?\b", q)
    if t:
        hour, minute = int(t.group(1)), int(t.group(2) or 0)
        if t.group(3) == "pm" and hour < 12:
            hour += 12
        elif not t.group(3) and hour < 8:
            hour += 12
        for m in cands:
            local = _start(m).astimezone()
            if (local.hour, local.minute) == (hour, minute) or (not t.group(2) and local.hour == hour):
                return m
    words = set(re.findall(r"\w+", q)) - {"the", "my", "meeting", "with", "for", "prep", "me"}
    scored = [(len(words & set(re.findall(r"\w+", (m.meta.get("title") or "").lower()))), m) for m in cands]
    best = max(scored, key=lambda x: x[0])
    return best[1] if best[0] else None


def header(m: Meeting) -> str:
    start, end = _start(m).astimezone(), datetime.fromisoformat(m.meta["end"]).astimezone()
    minutes = int((end - start).total_seconds() // 60)
    return f"{start:%-I:%M %p} · {m.meta.get('title')} · {minutes} min"


def _people_lines(ctx: Ctx, m: Meeting, directory: PeopleDirectory) -> list[str]:
    ids = m.meta.get("attendees") or []
    if m.meta.get("type") == "all_hands":
        return [f"{len(ids) + 1} people invited."]
    lines = []
    for eid in ids:
        meta = directory.meta.get(eid, {})
        bits = [directory.name(eid)]
        facts = directory.facts(ctx.home, eid)
        if meta.get("role"):
            bits.append(meta["role"])
        elif facts:
            bits.append(facts[0]["text"])
        ids = directory.identifiers(eid)
        talked = ctx.index.chunks_with_people(ids, limit=1, before=ctx.now.isoformat()) if ids else []
        if talked:
            bits.append(f"last talked {short_date(talked[0]['ts'])}")
        else:
            bits.append(f"New: no history yet ({meta.get('org', 'unknown org')})")
        lines.append(" · ".join(bits))
    return lines


def _previous(ctx: Ctx, m: Meeting) -> Meeting | None:
    if not m.meta.get("series_id"):
        return None
    prev = [x for x in load_meetings(ctx.home) if x.meta.get("series_id") == m.meta["series_id"]
            and _start(x) < _start(m) and x.meta.get("status") != "cancelled"]
    return max(prev, key=_start) if prev else None


def gather(ctx: Ctx, m: Meeting, directory: PeopleDirectory) -> tuple[Packet, str]:
    p = Packet()
    kind = m.meta.get("type", "standard")
    for c in ctx.index.chunks_of(f"sources/calendar/{m.meta['event_id']}.json"):
        p.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
    extra = []
    for fid in m.meta.get("linked_docs") or []:
        for c in ctx.index.chunks_of(f"sources/drive/{fid}.json")[:4]:
            p.add(c["path"], c["chunk_id"], c["text"], label=f"Attached {c['label']}", ts=c["ts"])
    since = (ctx.now - timedelta(days=30)).isoformat()
    if kind == "one_on_one":
        prev = _previous(ctx, m)
        if prev:
            since = prev.meta["start"]
            extra.append(f"The previous 1:1 was {short_date(prev.meta['start'])}.")
            for c in ctx.index.chunks_of(prev.rel_path):
                p.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
    if kind != "all_hands" and kind != "standup":
        for eid in m.meta.get("attendees") or []:
            for c in ctx.index.chunks_of(f"people/{eid}.md")[:3]:
                p.add(c["path"], c["chunk_id"], c["text"], label=c["label"])
            for c in ctx.index.chunks_with_people(directory.identifiers(eid), limit=12, before=ctx.now.isoformat()):
                if (c["ts"] or "") >= since and c["source"] not in ("briefings", "loops"):
                    p.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
                if len(p.items) > 24:
                    break
    if kind == "standup":
        mine = [h for h in search(ctx.index, "I did finished shipped worked on today", k=20,
                                  since=(ctx.now - timedelta(days=3)).isoformat())]
        for h in mine:
            p.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts)
    query = " ".join(filter(None, [m.meta.get("title")]))
    for h in search(ctx.index, query, k=6, since=(ctx.now - timedelta(days=60)).isoformat()):
        if h.source not in ("briefings", "loops"):
            p.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts)
    return p, " ".join(extra)


def _open_items(ctx: Ctx, m: Meeting) -> list:
    from archie.ask.intents.loops import _claim, _line

    ids = set(m.meta.get("attendees") or [])
    ranked = [r for r in rank(load_loops(ctx.home), ctx.now, ctx.config, upcoming_people=ids)
              if r.loop.meta.get("counterpart") in ids and not r.stale]
    return [_claim(ctx, r, _line(r)) for r in ranked[:6]]


def _standup_sections(ctx: Ctx) -> list[Section]:
    """Yesterday / Today / Blockers from structured data (no LLM)."""
    from archie.activity import my_activity
    from archie.ask.intents.ledger import _claim as item_claim
    from archie.ask.intents.loops import _claim, _line
    from archie.store.files import read_raw

    local = ctx.now.astimezone()
    back = 3 if local.weekday() == 0 else 1  # Monday looks back to Friday
    start = datetime.combine(local.date() - timedelta(days=back), datetime.min.time(), local.tzinfo)
    done = [i for i in my_activity(ctx, start, ctx.now) if i.kind not in ("email_sent", "meeting")]
    sections = [Section("Yesterday", items=[item_claim(ctx, i) for i in done] or [],
                        lines=[] if done else ["Nothing recorded in GitHub, Jira or Docs."])]
    today = []
    for p in sorted((ctx.home / "sources/jira").glob("*.json")):
        d = read_raw(p)
        if d.get("assignee_me") and d.get("status_category") == "indeterminate" and not d.get("deleted"):
            today.append(f"{d['key']} {d['summary']} ({d['status']})")
    ranked = [r for r in rank(load_loops(ctx.home), ctx.now, ctx.config) if not r.stale]
    due = [r for r in ranked if r.loop.meta.get("due") and r.loop.meta["due"] <= (local.date() + timedelta(days=1)).isoformat()]
    sections.append(Section("Today", lines=today, items=[_claim(ctx, r, _line(r)) for r in due[:5]]))
    fresh = [r for r in ranked if r.loop.meta["kind"] == "asked_of_me"
             and (ctx.now - datetime.fromisoformat(r.loop.meta["created_at"])) <= timedelta(hours=24)]
    if fresh:
        sections.append(Section("Blockers / new asks", items=[_claim(ctx, r, _line(r)) for r in fresh[:5]]))
    return sections


def _path(m: Meeting) -> str:
    s = _start(m).astimezone()
    return f"briefings/{s:%Y-%m-%d}/{s:%H%M}-{slug(m.meta.get('title') or 'meeting')[:40].replace('_', '-')}.md"


def build_briefing(ctx: Ctx, m: Meeting, force: bool = False) -> Briefing:
    directory = PeopleDirectory.load(ctx.home)
    packet, extra = gather(ctx, m, directory)
    people = _people_lines(ctx, m, directory)
    open_items = _open_items(ctx, m)
    fingerprint = "\n".join([packet.render(), "\n".join(people), "\n".join(c.text for c in open_items),
                             repr(sorted((k, str(v)) for k, v in m.meta.items()))])
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    rel = _path(m)
    path = ctx.home / rel
    if path.exists() and not force:
        saved = read_note(path)
        if saved.meta.get("packet_hash") == digest:
            return Briefing(m, Answer(plain=saved.body.strip()), rel, reused=True)
    kind = m.meta.get("type", "standard")
    me = ctx.me.name or "the user"
    answer = synthesize(ctx, f"Brief me for this meeting: {m.meta.get('title')}", packet,
                        INSTRUCTIONS.get(kind, INSTRUCTIONS["standard"]).replace("{me_name}", me),
                        extra_context=f"Meeting: {header(m)}. Type: {kind.replace('_', ' ')}. "
                                      f"Attendees: {', '.join(m.meta.get('attendee_names') or [])}. {extra}")
    answer.title = header(m)
    if kind == "standup":
        answer.sections[0:0] = _standup_sections(ctx)
    answer.sections.insert(0, Section("People", lines=people))
    if open_items:
        answer.sections.insert(1, Section("Open with these people", items=open_items))
    built = ctx.now.astimezone()
    answer.notes.append(f"Built {built:%-I:%M %p}.")
    old = read_note(path).meta if path.exists() else {}
    meta = {"event_id": m.meta["event_id"], "title": m.meta.get("title"), "start": m.meta["start"],
            "type": kind, "built_at": ctx.now.isoformat(), "packet_hash": digest,
            "notified": old.get("notified", False)}
    write_note(path, Note(meta=meta, body=render(answer, sources=True) + "\n"))
    return Briefing(m, answer, rel)

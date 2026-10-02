"""`notes`: the user hands Archie notes from a meeting (Vignette H).

The text is stored verbatim under `## My notes` of the matching meeting (the user's own
words, so it goes outside the fence). Action items are extracted with verified quotes and
become loops: the user's own items are i_promised; other people's are waiting_on.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.derive.loops import Loop, _history, save_loop
from archie.derive.meetings import Meeting, load_meetings
from archie.derive.people import PeopleDirectory, slug
from archie.index.chunk import chunk_file
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet, check_quote
from archie.store.fence import set_fence
from archie.store.files import Note, read_note, write_note

SCHEMA = {
    "title": "notes_actions",
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"owner": {"type": "string"}, "text": {"type": "string"}, "due": {"type": ["string", "null"]},
                       "quote": {"type": "string"}},
        "required": ["owner", "text", "due", "quote"], "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}


def _recent(ctx: Ctx) -> list[Meeting]:
    lo, hi = ctx.now - timedelta(hours=24), ctx.now + timedelta(hours=1)
    ms = [m for m in load_meetings(ctx.home) if lo <= datetime.fromisoformat(m.meta["start"]) <= hi
          and m.meta.get("status") != "cancelled"]
    return sorted(ms, key=lambda m: m.meta["start"], reverse=True)


def _match(ctx: Ctx, text: str | None) -> Meeting | None:
    recent = _recent(ctx)
    if not text:
        return recent[0] if recent else None
    words = set(re.findall(r"\w+", text.lower())) - {"the", "my", "meeting", "with", "from", "notes"}
    scored = [(len(words & set(re.findall(r"\w+", (m.meta.get("title") or "").lower()))), m) for m in recent]
    best = max(scored, key=lambda x: x[0], default=(0, None))
    return best[1] if best[0] else None


def _note_text(question: str, params: dict) -> str:
    if params.get("text"):
        return params["text"].strip()
    return question.split(":", 1)[1].strip() if ":" in question else question.strip()


def _append(ctx: Ctx, rel: str, text: str) -> None:
    path = ctx.home / rel
    note = read_note(path)
    stamp = ctx.now.astimezone().strftime("%b %-d, %-I:%M %p")
    entry = f"{text}\n_(added {stamp})_\n"
    if "## My notes\n" in note.body:
        head, tail = note.body.split("## My notes\n", 1)
        tail = tail.lstrip("\n")
        note.body = f"{head}## My notes\n{entry}\n{tail}"
    else:
        note.body = f"## My notes\n{entry}\n{note.body}"
    write_note(path, note)


def _standalone(ctx: Ctx, title: str) -> str:
    local = ctx.now.astimezone()
    rel = f"meetings/{local:%Y}/{local:%Y-%m-%d}-{slug(title)[:40].replace('_', '-')}.md"
    if not (ctx.home / rel).exists():
        meta = {"title": title, "start": ctx.now.isoformat(), "end": ctx.now.isoformat(), "type": "standard",
                "attendees": [], "attendee_names": [], "status": "notes_only"}
        note = Note(meta=meta, body="## My notes\n\n")
        note.body = set_fence(note.body, "## Decisions\n\n## Action items\n")
        write_note(ctx.home / rel, note)
    return rel


def _counterpart(owner: str, meeting_meta: dict, directory: PeopleDirectory) -> tuple[str, str]:
    attendees = meeting_meta.get("attendees") or []
    hits = [e for e in directory.find(owner) if e in attendees] or directory.find(owner)
    if len(hits) == 1:
        return hits[0], directory.name(hits[0])
    return slug(owner), owner


@intent("notes")
def notes_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    text = _note_text(question, params)
    if not text:
        return Answer(plain="Paste the notes after a colon, e.g. \"notes from the design review: …\"")
    meeting = _match(ctx, params.get("meeting"))
    rel = meeting.rel_path if meeting else _standalone(ctx, (params.get("meeting") or "Notes").strip().capitalize())
    title = meeting.meta.get("title") if meeting else read_note(ctx.home / rel).meta.get("title")
    _append(ctx, rel, text)

    packet = Packet()
    packet.add(rel, "notes", text, label=f"Your notes: {title}")
    local = ctx.now.astimezone()
    system = load_prompt("notes_actions", me_name=ctx.me.name or "the user", today=local.date().isoformat(),
                         weekday=local.strftime("%A"))
    out = ctx.backend.complete(system, f"Notes:\n{text}", SCHEMA, tier="fast")
    note = read_note(ctx.home / rel)
    chunks = chunk_file(rel, (ctx.home / rel).read_text())
    directory = PeopleDirectory.load(ctx.home)
    created = []
    for item in out.get("items") or []:
        cite = check_quote(packet, 1, item.get("quote", ""))
        if cite is None:
            continue
        chunk = next((c.chunk_id for c in chunks if item["quote"] in c.text), "c0")
        mine = item.get("owner", "").strip().lower() in ("me", "i", "myself") or ctx.me.mentioned_in(item["owner"])
        kind = "i_promised" if mine else "waiting_on"
        if mine:
            cp_id, cp_name = (meeting.meta["attendees"][0], directory.name(meeting.meta["attendees"][0])) \
                if meeting and meeting.meta.get("attendees") and len(meeting.meta["attendees"]) == 1 else (rel, title)
        else:
            cp_id, cp_name = _counterpart(item["owner"], note.meta, directory)
        h = hashlib.sha1(f"{rel}|{kind}|{item['quote']}".encode()).hexdigest()[:6]
        loop_id = f"loop-{local:%Y%m%d-%H%M}-{slug(cp_name)[:24]}-{h}"
        meta = {"loop_id": loop_id, "kind": kind, "status": "open", "counterpart": cp_id, "counterpart_name": cp_name,
                "summary": item.get("text", "").strip(), "created_at": ctx.now.isoformat(),
                "due": item.get("due"), "snoozed_until": None, "thread": rel, "addressed": "to",
                "sources": [{"file": rel, "chunk": chunk, "quote": item["quote"]}], "closed_by": None}
        loop = Loop(loop_id, f"loops/{local:%Y}/{loop_id}.md", Note(meta=meta, body=""))
        _history(loop, f"{local:%Y-%m-%d %H:%M} from your notes on {title}")
        save_loop(ctx.home, loop)
        owner = "you" if mine else cp_name
        created.append(f"- [{owner}] {meta['summary']}" + (f" (due {meta['due']})" if meta["due"] else ""))
    if created:
        note = read_note(ctx.home / rel)
        note.body = set_fence(note.body, "## Decisions\n\n## Action items\n" + "\n".join(created) + "\n")
        write_note(ctx.home / rel, note)
    ctx.index.sync()
    n = len(created)
    lines = [f"Saved your notes to {title}."]
    if n:
        lines.append(f"Tracking {n} action item{'s' if n != 1 else ''}:")
        lines += [f"  {c[2:]}" for c in created]
    return Answer(plain="\n".join(lines))

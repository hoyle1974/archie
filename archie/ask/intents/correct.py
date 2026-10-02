"""`correct`: the user fixes Archie in plain English. Every correction lands in a file the
user can see and edit: config/meeting_types.yaml, or a dossier's frontmatter."""

from __future__ import annotations

import yaml

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.briefings.build import pick_meeting
from archie.briefings.classify import TYPES
from archie.derive.meetings import load_meetings, recent_or_upcoming
from archie.derive.people import PeopleDirectory
from archie.llm.prompts import load_prompt
from archie.store.files import atomic_write, read_note, write_note

SCHEMA = {
    "title": "correct",
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": ["meeting_type", "same_person", "role"]},
                   **{k: {"type": ["string", "null"]} for k in ("meeting", "meeting_type", "alias", "person", "role")}},
    "required": ["kind", "meeting", "meeting_type", "alias", "person", "role"],
    "additionalProperties": False,
}
NAMES = {"one_on_one": "1:1", "standup": "standup", "all_hands": "all-hands", "standard": "regular meeting"}


def _meeting_type(ctx: Ctx, out: dict) -> Answer:
    kind = out.get("meeting_type")
    if kind not in TYPES:
        return Answer(plain="Which kind of meeting is it: 1:1, standup, all-hands, or regular?")
    m = recent_or_upcoming(ctx, out.get("meeting")) or pick_meeting(ctx, out.get("meeting"))
    if m is None:
        return Answer(plain="I couldn't tell which meeting you mean. Name it, e.g. \"the Friday sync is a standup\".")
    path = ctx.home / "config/meeting_types.yaml"
    data = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    if m.meta.get("series_id"):
        data.setdefault("series", {})[m.meta["series_id"]] = kind
        scope = "every meeting in that series"
    else:
        data.setdefault("titles", {})[m.meta["title"]] = kind
        scope = "meetings with that title"
    atomic_write(path, yaml.safe_dump(data, sort_keys=True, allow_unicode=True))
    for x in load_meetings(ctx.home):
        same = (m.meta.get("series_id") and x.meta.get("series_id") == m.meta["series_id"]) or \
               (not m.meta.get("series_id") and x.meta.get("title") == m.meta["title"])
        if same:
            x.meta["type"] = kind
            write_note(ctx.home / x.rel_path, x.note)
    return Answer(plain=f"Got it: {m.meta['title']} is a {NAMES[kind]}. I'll treat {scope} that way.")


def _person(ctx: Ctx, name: str | None) -> tuple[PeopleDirectory, str | None, str]:
    d = PeopleDirectory.load(ctx.home)
    hits = d.find(name or "")
    if len(hits) != 1:
        return d, None, ("Which one? " + ", ".join(d.name(h) for h in hits)) if hits else \
            f"I don't know anyone called {name} yet."
    return d, hits[0], ""


@intent("correct")
def correct_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    out = ctx.backend.complete(load_prompt("correct", me_name=ctx.me.name or "the user"), question, SCHEMA)
    if out["kind"] == "meeting_type":
        return _meeting_type(ctx, out)
    d, eid, problem = _person(ctx, out.get("person"))
    if not eid:
        return Answer(plain=problem)
    path = ctx.home / f"people/{eid}.md"
    note = read_note(path)
    if out["kind"] == "role":
        note.meta["role"] = (out.get("role") or "").strip()
        write_note(path, note)
        return Answer(plain=f"Got it: {d.name(eid)} is {note.meta['role']}.")
    alias = (out.get("alias") or "").strip()
    if not alias:
        return Answer(plain="What's the other name?")
    aliases = list(note.meta.get("aliases") or [])
    if alias not in aliases:
        aliases.append(alias)
    other = [h for h in d.find(alias) if h != eid]
    for o in other:  # the user said they're the same person: fold the other dossier in, visibly
        opath = ctx.home / f"people/{o}.md"
        onote = read_note(opath)
        aliases += [a for a in onote.meta.get("aliases") or [] if a not in aliases]
        onote.meta.update(status="merged", merged_into=eid)
        write_note(opath, onote)
    note.meta["aliases"] = aliases
    write_note(path, note)
    merged = f" I merged {', '.join(d.name(o) for o in other)} into them." if other else ""
    return Answer(plain=f"Got it: {alias} is {d.name(eid)}.{merged}")

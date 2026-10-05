"""Apply what the user tells Archie about people ("Goodspouse is my wife", "Acorn is my
youngest, he's three"). Works for several people at once and for people who never email.

Each person's sentence is saved word for word in their dossier's `## My notes` (the user's
own words, outside the fence) only if it really appears in the message. Relationship,
role, pronouns, full name and other names go in frontmatter, where the user can edit them."""

from __future__ import annotations

import copy

from archie.ask.context import Ctx
from archie.derive.people import PeopleDirectory, best_name
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Record, Shape
from archie.llm.verify import normalize
from archie.store.files import Note, read_note, write_note

REMEMBER_VERSION = 1  # bump when apply_facts or the remember instructions change
SHAPE = Shape("remember", records=(Record("PERSON", "people", F("name"), (
    F("relationship", required=False), F("role", required=False), F("pronouns", required=False),
    F("identity", required=False), F("avoid", "list", required=False), F("full_name", required=False),
    F("other_names", "list", required=False),
    F("statement", "quote", hint="their sentence(s) from the message"))),),
    example="PERSON Goodspouse\nrelationship: wife\nrole: -\npronouns: she/her\nidentity: -\navoid: -\n"
            "full_name: Goodspouse Mae Testerson\nother_names: Belle\nstatement: Goodspouse is my wife.")


def _new_person(ctx: Ctx, directory: PeopleDirectory, name: str) -> str:
    eid = directory.new_id(name, name)
    now = ctx.now.isoformat()
    meta = {"entity_id": eid, "name": name, "aliases": [], "org": None, "status": "known",
            "first_seen": now, "last_interaction": None}
    write_note(ctx.home / f"people/{eid}.md", Note(meta=meta, body="## My notes\n\n"))
    directory.add(eid, meta)
    return eid


def _add_note(note: Note, statement: str, when: str) -> None:
    line = f"- {statement.strip()} _(you said, {when})_\n"
    if normalize(statement) in normalize(note.body):
        return
    if "## My notes\n" in note.body:
        head, tail = note.body.split("## My notes\n", 1)
        note.body = f"{head}## My notes\n{line}{tail.lstrip(chr(10)) if tail.startswith(chr(10)) else tail}"
    else:
        note.body = f"## My notes\n{line}\n{note.body}"


def _content(note: Note) -> tuple[dict, str]:
    return {k: v for k, v in note.meta.items() if k != "facts_stale"}, note.body


def apply_facts(ctx: Ctx, question: str, people: list[dict], changed_only: bool = False) -> list[str]:
    directory = PeopleDirectory.load(ctx.home)
    when = ctx.now.astimezone().strftime("%b %-d")
    done, asks = [], []
    for p in people:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        full = (p.get("full_name") or "").strip()
        if full and normalize(full) not in normalize(question):  # only a full name the user really gave
            full = ""
        hits = directory.find(name)
        for other in [*(p.get("other_names") or []), *([full] if full else [])]:
            hits = hits or directory.find(other)
        if len(hits) > 1:
            asks.append(f"Which {name}? " + ", ".join(directory.name(h) for h in hits))
            continue
        eid = hits[0] if hits else _new_person(ctx, directory, best_name({name, *(p.get("other_names") or [])}) or name)
        # the name the user uses stays the name; a full name is kept beside it and shown in brackets
        path = ctx.home / f"people/{eid}.md"
        note = read_note(path)
        before = copy.deepcopy(_content(note))
        for key in ("relationship", "role", "pronouns", "identity"):
            if p.get(key):
                note.meta[key] = p[key].strip()
        if p.get("avoid"):
            note.meta["avoid"] = sorted(set(note.meta.get("avoid") or []) | {w.strip().lower() for w in p["avoid"]})
        if full:
            note.meta["full_name"] = full
        note.meta["facts_stale"] = True  # Archie's extracted facts get redone against what you said
        aliases = list(note.meta.get("aliases") or [])
        for a in [name, *(p.get("other_names") or []), *([full] if full else [])]:
            if a and a not in aliases and a != note.meta.get("name"):
                aliases.append(a)
        note.meta["aliases"] = aliases
        statement = p.get("statement") or ""
        if statement and normalize(statement) in normalize(question):  # only the user's real words
            _add_note(note, statement, when)
        if changed_only and _content(note) == before:  # a replay that changes nothing writes nothing
            continue
        write_note(path, note)
        directory.add(eid, note.meta)
        bits = [b for b in (p.get("relationship"), p.get("identity"), p.get("role"), p.get("pronouns")) if b]
        done.append(f"{directory.label(eid)}" + (f": {', '.join(bits)}" if bits else "") + ("" if hits else ", new"))
    return done + asks


def remember_people(ctx: Ctx, said: str, changed_only: bool = False) -> list[str]:
    """Apply what the user said about people; one line per person changed (or a "Which …?").
    `changed_only` (replays): skip people the sentence no longer changes."""
    out = ctx.backend.complete(load_prompt("remember", me_name=ctx.me.name or "the user"), said, SHAPE)
    return apply_facts(ctx, said, out.get("people") or [], changed_only=changed_only)

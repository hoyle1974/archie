"""`remember`: the user tells Archie about people ("Goodspouse is my wife", "Acorn is my
youngest, he's three"). Works for several people at once and for people who never email.

Each person's sentence is saved word for word in their dossier's `## My notes` (the user's
own words, outside the fence) only if it really appears in the message. Relationship,
role, pronouns and other names go in frontmatter, where the user can edit them."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.derive.people import PeopleDirectory, best_name
from archie.llm.prompts import load_prompt
from archie.llm.verify import normalize
from archie.store.files import Note, read_note, write_note

SCHEMA = {
    "title": "remember",
    "type": "object",
    "properties": {"people": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "relationship": {"type": ["string", "null"]},
                       "role": {"type": ["string", "null"]}, "pronouns": {"type": ["string", "null"]},
                       "other_names": {"type": "array", "items": {"type": "string"}},
                       "statement": {"type": "string"}},
        "required": ["name", "relationship", "role", "pronouns", "other_names", "statement"],
        "additionalProperties": False}}},
    "required": ["people"],
    "additionalProperties": False,
}


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


def apply_facts(ctx: Ctx, question: str, people: list[dict]) -> list[str]:
    directory = PeopleDirectory.load(ctx.home)
    when = ctx.now.astimezone().strftime("%b %-d")
    done, asks = [], []
    for p in people:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        hits = directory.find(name)
        for other in p.get("other_names") or []:
            hits = hits or directory.find(other)
        if len(hits) > 1:
            asks.append(f"Which {name}? " + ", ".join(directory.name(h) for h in hits))
            continue
        eid = hits[0] if hits else _new_person(ctx, directory, best_name({name, *(p.get("other_names") or [])}) or name)
        path = ctx.home / f"people/{eid}.md"
        note = read_note(path)
        for key in ("relationship", "role", "pronouns"):
            if p.get(key):
                note.meta[key] = p[key].strip()
        aliases = list(note.meta.get("aliases") or [])
        for a in [name, *(p.get("other_names") or [])]:
            if a and a not in aliases and a != note.meta.get("name"):
                aliases.append(a)
        note.meta["aliases"] = aliases
        statement = p.get("statement") or ""
        if statement and normalize(statement) in normalize(question):  # only the user's real words
            _add_note(note, statement, when)
        write_note(path, note)
        directory.add(eid, note.meta)
        bits = [b for b in (p.get("relationship"), p.get("role"), p.get("pronouns")) if b]
        done.append(f"{directory.name(eid)}" + (f" ({', '.join(bits)})" if bits else "") + ("" if hits else ", new"))
    return done + asks


@intent("remember")
def remember_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    out = ctx.backend.complete(load_prompt("remember", me_name=ctx.me.name or "the user"), question, SCHEMA)
    lines = apply_facts(ctx, question, out.get("people") or [])
    if not lines:
        return Answer(plain="I didn't catch who that was about. Try \"Goodspouse is my wife\".")
    return Answer(plain="Got it. I'll remember:\n" + "\n".join(f"  • {x}" for x in lines))

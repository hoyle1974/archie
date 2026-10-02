"""Lasting, cited facts about people for the dossier's "What Archie knows" (DESIGN §4.2).

Runs after indexing, only for people with newer material than last time
(state/people_enriched.yaml). Facts accumulate (deduplicated, newest kept, at most 8),
each with a verified quote. They live inside the fence; the user's notes are untouched.
"""

from __future__ import annotations

import yaml

from archie.ask.context import Ctx
from archie.derive.people import PeopleDirectory, parse_facts, render_facts
from archie.llm.backend import LLMError
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet, check_quote, normalize
from archie.store.fence import get_fence, set_fence
from archie.store.files import atomic_write, read_note, write_note

MAX_FACTS = 8
SCHEMA = {
    "title": "people_facts",
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object", "properties": {"text": {"type": "string"}, "ref": {"type": "integer"},
                                         "quote": {"type": "string"}},
        "required": ["text", "ref", "quote"], "additionalProperties": False}}},
    "required": ["facts"],
    "additionalProperties": False,
}
def enrich_people(ctx: Ctx, paths=None) -> None:
    state_file = ctx.home / "state/people_enriched.yaml"
    done = (yaml.safe_load(state_file.read_text()) or {}) if state_file.exists() else {}
    directory = PeopleDirectory.load(ctx.home)
    changed = False
    for eid in sorted(directory.meta):
        ids = directory.identifiers(eid)
        recent = [c for c in ctx.index.chunks_with_people(ids, limit=12, before=ctx.now.isoformat())
                  if c["source"] not in ("briefings", "loops", "people")]
        newest = max((c["ts"] or "" for c in recent), default="")
        if not recent or newest <= done.get(eid, ""):
            continue
        name = directory.name(eid)
        packet = Packet()
        for c in recent:
            packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
        system = load_prompt("people_facts", person=name, me_name=ctx.me.name or "the user")
        try:
            out = ctx.backend.complete(system, f"Sources about {name}:\n\n{packet.render()}", SCHEMA, tier="fast")
        except LLMError:
            continue
        path = ctx.home / f"people/{eid}.md"
        note = read_note(path)
        facts = parse_facts(get_fence(note.body))
        for f in out.get("facts") or []:
            cite = check_quote(packet, int(f.get("ref", 0)), f.get("quote", ""))
            if cite is None or not f.get("text"):
                continue
            new = {"text": f["text"].strip().rstrip("."), "file": cite.path, "chunk": cite.chunk_id,
                   "quote": cite.quote.replace('"', "'")}
            facts = [x for x in facts if normalize(x["text"]) != normalize(new["text"])] + [new]
        note.body = set_fence(note.body, render_facts(note.meta, facts[-MAX_FACTS:]))
        write_note(path, note)
        done[eid] = newest
        changed = True
    if changed:
        atomic_write(state_file, yaml.safe_dump(done, sort_keys=True))

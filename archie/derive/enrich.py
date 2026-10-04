"""Lasting, cited facts about people for the dossier's "What Archie knows" (DESIGN §4.2).

Runs after indexing, only for people with newer material than last time
(state/people_enriched.yaml), or whose facts were written by an older version of the
instructions (`_prompt` in that file), so a fix to the instructions reaches every dossier. Facts accumulate (deduplicated, newest kept, at most 8),
each with a verified quote. They live inside the fence; the user's notes are untouched.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

import yaml

from archie.ask.context import Ctx
from archie.derive.failures import Failures
from archie.derive.people import PeopleDirectory, parse_facts, render_facts
from archie.llm.backend import LLMError
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Record, Shape
from archie.llm.verify import Packet, check_quote, normalize
from archie.store.fence import get_fence, set_fence
from archie.store.files import atomic_write, read_note, write_note

MAX_FACTS = 8
INSTRUCTIONS_VERSION = 2  # bump when the instructions written below in code change
OLD_DAYS = 365  # sources older than this are written about in the past tense
SHAPE = Shape("people_facts", records=(Record("FACT", "facts", F("text", hint="short phrase"),
                                              (F("cite", "cite"),)),),
              example='FACT Product manager for auth\ncite: [2] "I\'m the PM for auth"')


def prompt_version() -> str:
    """Changes whenever people_facts.md, the reply shape or INSTRUCTIONS_VERSION changes."""
    text = f"{INSTRUCTIONS_VERSION}\n{load_prompt('people_facts')}\n{SHAPE!r}"
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _uses(text: str, words: set[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE) for w in words)


def _enrich_one(ctx: Ctx, directory: PeopleDirectory, eid: str, since: str, failures: Failures,
                fresh: bool = False) -> str | None:
    """Update one dossier; returns the newest chunk time considered, or None if skipped.
    `fresh`: the facts were written by older instructions, so redo them from scratch."""
    if fresh or directory.meta.get(eid, {}).get("facts_stale"):
        since = ""  # the user told us something, or the instructions changed: redo from scratch
    recent = [c for c in ctx.index.chunks_with_people(directory.identifiers(eid), limit=12, before=ctx.now.isoformat())
              if c["source"] not in ("briefings", "loops", "people")]
    if not recent:
        return None
    packet = Packet()
    for c in recent:
        packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
    from archie.ask.synthesize import describe, packet_text, people_context

    avoid = directory.avoided_words([eid, *directory.mentioned_in(packet_text(packet))])
    path = ctx.home / f"people/{eid}.md"
    if any(_uses(f["text"], avoid) for f in parse_facts(get_fence(read_note(path).body))):
        since = ""  # an old fact uses a word the user ruled out: redo against what they said
    newest = max((c["ts"] or "" for c in recent), default="")
    if newest <= since or failures.gave_up(f"people:{eid}", newest):
        return None
    name = directory.name(eid)
    system = load_prompt("people_facts", person=name, me_name=ctx.me.name or "the user")
    told = describe(directory.meta.get(eid, {}), name)
    mine = read_note(path).body.split("<!-- archie:auto -->")[0].replace("## My notes", "").strip()
    if told or mine:
        system += ("\n\nWhat the user has told you about them is ground truth. Never state a fact that "
                   "contradicts it (e.g. if they say 'my child', never write 'son'). Don't repeat it "
                   "(Archie shows it in their own words); add what the sources show beyond it: where they "
                   "work or study, what they do, what they care about.\n"
                   + (f"Stated: {told}\n" if told else "") + (f"Their notes:\n{mine}" if mine else ""))
    if newest and (ctx.now - datetime.fromisoformat(newest).replace(tzinfo=ctx.now.tzinfo)).days > OLD_DAYS:
        system += (f"\n\nThe newest source is from {newest[:4]}, over a year ago. Write each fact in the past "
                   f"tense with its year (\"In {newest[:4]}, handled your app issue\"), never as if it's current.")
    user = f"{people_context(ctx, packet)}\n\nSources about {name}:\n\n{packet.render()}".lstrip()
    try:
        out = ctx.backend.complete(system, user, SHAPE, tier="fast")
    except LLMError as exc:
        failures.failed(f"people:{eid}", newest, exc)
        return None
    failures.ok(f"people:{eid}")
    note = read_note(path)
    stale = note.meta.pop("facts_stale", None)
    facts = [] if stale or fresh else [f for f in parse_facts(get_fence(note.body)) if not _uses(f["text"], avoid)]
    for f in out.get("facts") or []:
        cite = check_quote(packet, int(f.get("ref", 0)), f.get("quote", ""))
        if cite is None or not f.get("text") or _uses(f["text"], avoid):
            continue
        new = {"text": f["text"].strip().rstrip("."), "file": cite.path, "chunk": cite.chunk_id,
               "quote": cite.quote.replace('"', "'")}
        facts = [x for x in facts if normalize(x["text"]) != normalize(new["text"])] + [new]
    note.body = set_fence(note.body, render_facts(note.meta, facts[-MAX_FACTS:]))
    write_note(path, note)
    return newest


def enrich_people(ctx: Ctx, paths=None) -> None:
    from concurrent.futures import ThreadPoolExecutor

    state_file = ctx.home / "state/people_enriched.yaml"
    done = (yaml.safe_load(state_file.read_text()) or {}) if state_file.exists() else {}
    versions = done.pop("_prompt", None) or {}  # entity_id -> prompt_version() its facts were written with
    version = prompt_version()
    directory = PeopleDirectory.load(ctx.home)
    ids = sorted(directory.meta)
    failures = Failures(ctx.home)
    workers = max(1, int(ctx.config["llm"].get("parallel", 1)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda e: _enrich_one(ctx, directory, e, done.get(e, ""), failures,
                                                      fresh=versions.get(e) != version), ids))
    failures.save()
    updated = {e: r for e, r in zip(ids, results) if r}
    if updated:
        done.update(updated)
        versions.update({e: version for e in updated})
        atomic_write(state_file, yaml.safe_dump({**done, "_prompt": versions}, sort_keys=True))

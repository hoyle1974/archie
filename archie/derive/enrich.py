"""Lasting, cited facts about people for the dossier's "What Archie knows" (DESIGN §4.2).

Runs after indexing, only for people with newer material than last time
(state/people_enriched.yaml), or whose facts were written by an older version of the
instructions (`_prompt` in that file), so a fix to the instructions reaches every dossier. Facts accumulate (deduplicated, newest kept, at most 8),
each with a verified quote. They live inside the fence; the user's notes are untouched.
"""

from __future__ import annotations

import re
from datetime import datetime

import yaml

from archie.ask.context import Ctx
from archie.derive.failures import Failures
from archie.derive.people import PeopleDirectory, parse_facts, render_facts
from archie.derive.versions import stamp
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
    return stamp("people_facts", INSTRUCTIONS_VERSION, load_prompt("people_facts"), repr(SHAPE))


def _batches(chunks: list[dict], max_chars: int) -> list[list[dict]]:
    """Oldest first, each batch within max_chars (a single bigger chunk gets its own batch)."""
    out, cur, used = [], [], 0
    for c in sorted(chunks, key=lambda c: c["ts"] or ""):
        if cur and used + len(c["text"]) > max_chars:
            out.append(cur)
            cur, used = [], 0
        cur.append(c)
        used += len(c["text"])
    return out + ([cur] if cur else [])


def _uses(text: str, words: set[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE) for w in words)


def _enrich_one(ctx: Ctx, directory: PeopleDirectory, eid: str, since: str, failures: Failures,
                fresh: bool = False) -> str | None:
    """Update one dossier; returns the newest chunk time considered, or None if skipped.
    A redo (new instructions, something the user told us, or an old fact using a ruled-out word)
    reads all of the person's material in batches; otherwise only what's newer than `since`.
    Nothing is written unless every batch succeeds."""
    from archie.ask.evidence import person_evidence
    from archie.ask.synthesize import describe, people_context

    path = ctx.home / f"people/{eid}.md"
    redo = fresh or bool(directory.meta.get(eid, {}).get("facts_stale"))
    everything = person_evidence(ctx, eid, max_items=100_000, max_chars=10**12)
    if not everything:
        return None
    avoid = directory.avoided_words(
        [eid, *directory.mentioned_in(" ".join(f"{c['label']} {c['text']}" for c in everything))])
    if any(_uses(f["text"], avoid) for f in parse_facts(get_fence(read_note(path).body))):
        redo = True
    chunks = everything if redo else [c for c in everything if (c["ts"] or "") > since]
    newest = max((c["ts"] or "" for c in everything), default="")
    if not chunks or failures.gave_up(f"people:{eid}", newest):
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
    note = read_note(path)
    facts = [] if redo else [f for f in parse_facts(get_fence(note.body)) if not _uses(f["text"], avoid)]
    for batch in _batches(chunks, int(ctx.config["people"]["facts_max_chars"])):
        packet = Packet()
        for c in batch:
            packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
        user = f"{people_context(ctx, packet)}\n\nSources about {name}:\n\n{packet.render()}".lstrip()
        try:
            out = ctx.backend.complete(system, user, SHAPE, tier="fast")
        except LLMError as exc:
            failures.failed(f"people:{eid}", newest, exc)
            return None
        for f in out.get("facts") or []:
            cite = check_quote(packet, int(f.get("ref", 0)), f.get("quote", ""))
            if cite is None or not f.get("text") or _uses(f["text"], avoid):
                continue
            new = {"text": f["text"].strip().rstrip("."), "file": cite.path, "chunk": cite.chunk_id,
                   "quote": cite.quote.replace('"', "'")}
            facts = [x for x in facts if normalize(x["text"]) != normalize(new["text"])] + [new]
    failures.ok(f"people:{eid}")
    note.meta.pop("facts_stale", None)
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

"""Fallback intent: hybrid search over everything, then a cited answer."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.synthesize import synthesize
from archie.derive.ignore import skipped_senders
from archie.derive.people import PeopleDirectory
from archie.index.search import rrf_scores, search
from archie.llm.verify import Packet, tidy

# "did Status reply?", "what did they say?", "do you see the message I sent them?"
CONVERSATION = re.compile(r"\b(repl\w*|respond\w*|said|say|says|told|wrote|message\w*|sent|hear\w*)\b"
                          r"|\btell (me|you)\b(?!\s+about)", re.I)  # not "tell me about my family"
THREAD_INSTRUCTIONS = """- This is about a conversation. Lead with its newest message: when, who wrote it, what it
  says, and whose turn it is now.
- Include {me_name}'s own latest message in it if the sources have it.
- Leave out older exchanges with the same people unless the question asks for history.
- At most 5 points in all."""
THREAD_LATEST = 3  # newest messages of the conversation always shown to the model


def packet_from_hits(hits) -> Packet:
    hits, notes = collapse_repeats(hits)
    p = Packet()
    for h in hits:
        p.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts, score=h.score, note=notes.get((h.path, h.chunk_id), ""))
    return p


def thread_packet(ctx: Ctx, hits) -> Packet:
    """The newest email thread among the hits, its latest messages first, then the other hits
    newest first. Search ranks by relevance, which put a 2023 thread ahead of yesterday's reply."""
    threads = {h.path for h in hits if h.source == "gmail"}
    chunks = {p: ctx.index.chunks_of(p) for p in threads}
    p = Packet()
    if chunks:
        newest = max(chunks, key=lambda path: max((c["ts"] or "" for c in chunks[path]), default=""))
        for c in sorted(chunks[newest], key=lambda c: c["ts"] or "", reverse=True)[:THREAD_LATEST]:
            p.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
    hits, notes = collapse_repeats(hits)
    for h in sorted(hits, key=lambda h: h.ts or "", reverse=True):
        p.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts, score=h.score, note=notes.get((h.path, h.chunk_id), ""))
    return p


PERSON_WEIGHT = 2.0  # the topic among a named person's own messages counts double


def _identifiers(ctx: Ctx, names: list[str]) -> list[str]:
    """Emails (and gh: logins) of the people named, when each name means exactly one person."""
    directory = PeopleDirectory.load(ctx.home)
    out: list[str] = []
    for name in names:
        found = directory.find(name)
        if len(found) == 1:
            out += directory.identifiers(found[0])
    return out


def limits(ctx: Ctx) -> tuple[int, int]:
    cfg = ctx.config.get("ask") or {}
    return int(cfg.get("max_sources", 40)), int(cfg.get("max_source_chars", 160_000))


def _fit(hits, max_chars: int) -> list:
    """Hits in order while their text fits in max_chars; one too big is skipped, not the rest."""
    out, used = [], 0
    for h in hits:
        if used + len(h.text) <= max_chars:
            out.append(h)
            used += len(h.text)
    return out


def _normalized(hits) -> list:
    top = max((h.score for h in hits), default=0) or 1.0
    for h in hits:
        h.score = h.score / top
    return hits


def _title(h) -> str:
    return h.label.rsplit(" (", 1)[0]


def collapse_repeats(hits) -> tuple[list, dict]:
    """One source per repeating calendar event ("Childone pick up" on nine Wednesdays): the
    best-ranked one stays, and the others' dates become its note. Returns (hits, notes by key)."""
    from archie.store.times import when

    groups: dict[str, list] = {}
    for h in hits:
        if h.source == "calendar":
            groups.setdefault(_title(h), []).append(h)
    keep, notes = [], {}
    for h in hits:
        group = groups.get(_title(h)) if h.source == "calendar" else None
        if group and len(group) > 1:
            if h is not group[0]:
                continue
            others = sorted(x.ts or "" for x in group[1:])
            dates = ", ".join(when(t) for t in others[:12]) + (f" and {len(others) - 12} more" if len(others) > 12 else "")
            notes[(h.path, h.chunk_id)] = f"(Repeats: also {dates}.)"
        keep.append(h)
    return keep, notes


def find(ctx: Ctx, question: str, params: dict) -> list:
    """The chunks for a question, best first, each with a 0–1 match score.

    "the message I sent them" searches only the user's own mail. Otherwise three searches
    are fused into one ranking (Reciprocal Rank Fusion): the topic among things the named
    people were part of (weighted double: their name as a word matched every "Goodspouse -
    Swimming" event instead), the topic with the names, and the whole question."""
    k, max_chars = limits(ctx)
    topic = params.get("topic")
    query = " ".join(filter(None, [topic, *params.get("people", [])])) or question
    window = {"since": params.get("since"), "until": params.get("until")}
    skip = skipped_senders(ctx, question)
    if params.get("mine"):
        for q in (query, question):
            hits = search(ctx.index, q, k=k, skip_senders=skip, senders=ctx.me.emails, **window)
            if hits:
                return _normalized(_fit(hits, max_chars))
    ids = _identifiers(ctx, params.get("people", []))
    tries = [(topic, ids, PERSON_WEIGHT)] if topic and ids else []
    tries += [(query, None, 1.0)] + ([(question, None, 1.0)] if question != query else [])
    rankings, weights, by_key = [], [], {}
    for q, people, weight in tries:
        found = search(ctx.index, q, k=k, skip_senders=skip, people=people, **window)
        rankings.append([(h.path, h.chunk_id) for h in found])
        weights.append(weight)
        for h in found:
            by_key.setdefault((h.path, h.chunk_id), h)
    scores = rrf_scores(rankings, weights=weights)
    hits = [by_key[key] for key in sorted(scores, key=lambda x: -scores[x])]
    for h in hits:
        h.score = scores[(h.path, h.chunk_id)]
    hits = [h for h in hits if tidy(h.text)]  # a notes file holding only its data block says nothing
    return _normalized(_fit(hits, max_chars)[:k])


@intent("search")
def search_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    hits = find(ctx, question, params)
    if not hits:
        return Answer(nothing_found=True)
    if CONVERSATION.search(question):
        instructions = THREAD_INSTRUCTIONS.replace("{me_name}", ctx.me.name or "the user")
        packet = packet_from_hits(sorted(hits, key=lambda h: h.ts or "", reverse=True)) if params.get("mine") \
            else thread_packet(ctx, hits)  # "the message I sent": only your own mail, newest first
        return synthesize(ctx, question, packet, instructions)
    return synthesize(ctx, question, packet_from_hits(hits))

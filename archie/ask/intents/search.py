"""Fallback intent: hybrid search over everything, then a cited answer."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.synthesize import synthesize
from archie.derive.ignore import skipped_senders
from archie.index.search import search
from archie.llm.verify import Packet


def packet_from_hits(hits) -> Packet:
    p = Packet()
    for h in hits:
        p.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts)
    return p


@intent("search")
def search_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    query = " ".join(filter(None, [params.get("topic"), *params.get("people", [])])) or question
    window = {"since": params.get("since"), "until": params.get("until")}
    skip = skipped_senders(ctx, question)
    tries = [(query, ctx.me.emails), (question, ctx.me.emails)] if params.get("mine") else []
    tries += [(query, None), (question, None)]
    hits = []
    for q, senders in tries:
        hits = search(ctx.index, q, k=8, skip_senders=skip, senders=senders, **window)
        if hits:
            break
    if not hits:
        return Answer(nothing_found=True)
    return synthesize(ctx, question, packet_from_hits(hits))

"""Fallback intent: hybrid search over everything, then a cited answer."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.synthesize import synthesize
from archie.derive.ignore import skipped_senders
from archie.index.search import search
from archie.llm.verify import Packet

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
    p = Packet()
    for h in hits:
        p.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts)
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
    for h in sorted(hits, key=lambda h: h.ts or "", reverse=True):
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
    if CONVERSATION.search(question):
        instructions = THREAD_INSTRUCTIONS.replace("{me_name}", ctx.me.name or "the user")
        packet = packet_from_hits(sorted(hits, key=lambda h: h.ts or "", reverse=True)) if params.get("mine") \
            else thread_packet(ctx, hits)  # "the message I sent": only your own mail, newest first
        return synthesize(ctx, question, packet, instructions)
    return synthesize(ctx, question, packet_from_hits(hits))

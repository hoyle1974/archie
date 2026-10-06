"""The one way to gather evidence about a person (spec: durable-fixes §2).

Order: chunks matching the topic (if any), then chunks the person sent, then the rest of
their chunks, each newest first, within an item count and a character budget. A chunk too
big for the room left is skipped, not the rest. A signature repeated across messages
counts once (the newest). Archie's own notes (dossiers, loops,
briefings) and saved web pages are left out; future meetings too."""

from __future__ import annotations

from archie.ask.context import Ctx
from archie.index.chunk import signature_key

SKIP = ("briefings", "loops", "people", "web")  # a public page naming them may be about a namesake


def person_chunks(ctx: Ctx, directory, entity_id: str, limit: int = 100_000, before: str | None = None) -> list[dict]:
    """Chunks a person is in, newest first: by email or handle, and for someone the user only
    mentioned (`origin: mentioned`), by their full name in the text (DESIGN §4.2)."""
    out = {(c["path"], c["chunk_id"]): c
           for c in ctx.index.chunks_with_people(directory.identifiers(entity_id), limit=limit, before=before)}
    for c in ctx.index.chunks_naming(directory.mention_names(entity_id), limit=limit, before=before):
        if c["source"] not in SKIP:  # their own dossier names them too
            out.setdefault((c["path"], c["chunk_id"]), c)
    return sorted(out.values(), key=lambda c: c["ts"] or "", reverse=True)[:limit]


def person_evidence(ctx: Ctx, entity_id: str, *, topic: str | None = None, max_items: int = 40,
                    max_chars: int = 160_000, since: str | None = None) -> list[dict]:
    from archie.derive.people import PeopleDirectory
    from archie.index.search import search

    directory = PeopleDirectory.load(ctx.home)
    ids = directory.identifiers(entity_id)
    if not (ids or directory.mention_names(entity_id)) or max_items <= 0:
        return []
    before = ctx.now.isoformat()
    theirs = [c for c in person_chunks(ctx, directory, entity_id, before=before)
              if c["source"] not in SKIP and (not since or (c["ts"] or "") > since)]
    by_key = {(c["path"], c["chunk_id"]): c for c in theirs}
    ordered: list[dict] = []
    if topic:
        hits = search(ctx.index, topic, k=max_items, people=ids, since=since, until=before)
        ordered += [by_key[(h.path, h.chunk_id)] for h in hits if (h.path, h.chunk_id) in by_key]
    senders = {i.lower() for i in ids}
    ordered += [c for c in theirs if (c.get("sender") or "").lower() in senders]
    ordered += theirs
    out, seen, used = [], set(), 0
    for c in ordered:
        key = (c["path"], c["chunk_id"])
        sig = signature_key(c["source"], c["chunk_id"], c.get("sender") or "", c["text"])
        if key in seen or (sig and sig in seen) or len(out) >= max_items:
            continue
        if used + len(c["text"]) > max_chars:
            continue
        seen |= {key, sig} - {None}
        out.append(c)
        used += len(c["text"])
    return out

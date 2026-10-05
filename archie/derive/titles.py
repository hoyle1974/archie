"""Titles from email signatures, read by code (spec: durable-fixes §3). Computed when asked,
from the person's own signature chunks; the raw mail is the source of truth."""

from __future__ import annotations

import re
from dataclasses import dataclass

from archie.ask.context import Ctx
from archie.index.chunk import short_date

_SKIP = re.compile(r"\d|@|https?://|www\.", re.I)


@dataclass
class Title:
    text: str
    date: str
    path: str
    chunk_id: str


def title_from_signature(sig: str, names: set[str], org: str | None) -> str | None:
    """The first line that reads like a title: not their name, a phone number, an address, a link,
    the company, "Sent from my …" or a one-word sign-off."""
    company = (org or "").lower().split(".")[0]
    for line in sig.splitlines():
        s = line.strip().strip("|•·-–— ").strip()
        low = s.lower()
        if not s or low.startswith("sent from") or _SKIP.search(s):
            continue
        if low in names or any(low.startswith(n + " ") or low == n for n in names if n):
            continue
        if company and low.replace(" ", "") == company:
            continue
        if 2 <= len(s.split()) <= 8 and not s.endswith(("!", "?")):
            return s
    return None


def titles(ctx: Ctx, entity_id: str) -> list[Title]:
    """The person's signature titles, newest first, one per distinct text."""
    from archie.derive.people import PeopleDirectory, org

    d = PeopleDirectory.load(ctx.home)
    meta = d.meta.get(entity_id) or {}
    ids = d.identifiers(entity_id)
    if not ids:
        return []
    names = {str(n).lower() for n in [meta.get("name"), meta.get("full_name"), *(meta.get("aliases") or [])]
             if n and "@" not in str(n)}
    names |= {n.split(" ")[0] for n in list(names) if " " in n}
    out: dict[str, Title] = {}
    for c in ctx.index.chunks_with_people(ids, limit=100_000, before=ctx.now.isoformat()):
        if c["source"] != "gmail" or not c["chunk_id"].startswith("s") or (c.get("sender") or "") not in ids:
            continue
        t = title_from_signature(c["text"], names, org(meta))
        if t and t.lower() not in out:
            out[t.lower()] = Title(t, c["ts"] or "", c["path"], c["chunk_id"])
    return list(out.values())


def role_line(ts: list[Title]) -> str | None:
    if not ts:
        return None
    if len(ts) == 1:
        return f"Role: {ts[0].text} (signed {short_date(ts[0].date)})"
    bits = [f"{t.text} ({short_date(t.date)})" for t in ts[:3]]
    return "Role: signs as " + (", ".join(bits[:-1]) + " and " + bits[-1])


def signature_context(ts: list[Title]) -> str:
    """A sentence for the model's context, so it reports every title with its date."""
    if not ts:
        return ""
    return (" Their email signatures say: " + "; ".join(f"{t.text} (signed {short_date(t.date)})" for t in ts)
            + ". If they differ, give both with dates; don't pick one.")

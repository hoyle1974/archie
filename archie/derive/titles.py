"""Titles from email signatures, read by code (spec: durable-fixes §3). Computed when asked,
from the person's own signature chunks; the raw mail is the source of truth."""

from __future__ import annotations

import re
from dataclasses import dataclass

from archie.ask.context import Ctx
from archie.index.chunk import is_signature, short_date

_SKIP = re.compile(r"\d|@|https?://|www\.", re.I)
# a title names a job; a line without one of these words (a company, a city, a motto, a mail
# app's footer, a disclaimer) is never shown as a role
_JOB = re.compile(
    r"\b(director|manager|engineer|developer|designer|architect|analyst|scientist|researcher|consultant|"
    r"specialist|coordinator|administrator|officer|president|vp|svp|evp|head|lead|chief|founder|co-founder|"
    r"owner|partner|principal|associate|assistant|intern|ceo|cto|cfo|coo|cpo|ciso|cmo|professor|teacher|"
    r"instructor|lecturer|counselor|coach|nurse|physician|doctor|attorney|lawyer|paralegal|accountant|"
    r"recruiter|editor|writer|producer|strategist|advisor|adviser|representative|executive|supervisor|"
    r"technician|therapist|psychologist|secretary|treasurer|chair|chairman|chairperson|dean|superintendent|"
    r"librarian|pastor|agent|broker|realtor|planner|staff|fellow|member|programmer|operator|clerk)s?\b", re.I)
_NOT = re.compile(r"^(sent|get|confidential|please|this (e-?mail|message))\b|[,.:;]$", re.I)


@dataclass
class Title:
    text: str
    date: str
    path: str
    chunk_id: str


def title_from_signature(sig: str, names: set[str], org: str | None) -> str | None:
    """The first line that names a job and isn't their name, a phone number, an address, a link,
    the company, a mail app's footer or a sign-off."""
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
        if len(s.split()) <= 8 and _JOB.search(s) and not _NOT.search(s) and not s.endswith(("!", "?")):
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
        if not is_signature(c["source"], c["chunk_id"]) or (c.get("sender") or "") not in ids:
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

"""Follow-ups that need no model call (spec: understand-first §2.4): "show 2" opens a
citation from the last answer, and "really?" asks the last question again."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.render import NOTHING

SHOW = re.compile(r"^\s*(?:show|open)(?: me)?(?: (?:source|citation))?\s*\[?(\d+)\]?\s*[.!?]?\s*$", re.I)
RECHECK = re.compile(r"^\s*(really|are you sure|you sure|is that right|is that true|double[- ]check( that)?)"
                     r"\s*[?!.]*\s*$", re.I)
CHECKED = "I checked again."
CHANGED = "This is different from my earlier answer."


def citation_number(text: str) -> int | None:
    m = SHOW.match(text or "")
    return int(m.group(1)) if m else None


def is_recheck(text: str) -> bool:
    return bool(RECHECK.match(text or ""))


def _around(text: str, quote: str, width: int = 200) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    q = re.sub(r"\s+", " ", quote or "").strip().lower()
    at = flat.lower().find(q[:40]) if q else -1
    if at < 0:
        return flat[: 2 * width]
    start, end = max(0, at - width), min(len(flat), at + len(q) + width)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def show(ctx: Ctx, last: dict | None, n: int) -> Answer:
    cites = (last or {}).get("citations") or []
    if not cites:
        return Answer(plain="There's no recent answer with sources to show.")
    c = next((c for c in cites if c.get("n") == n), None)
    if c is None:
        return Answer(plain=f"The last answer has citations 1–{len(cites)}.")
    lines = [f"[{n}] {c.get('label') or c['file']}", f"“{c.get('quote', '')}”"]
    around = _around(ctx.index.chunk_text(c["file"], c["chunk"]) or "", c.get("quote", ""))
    if around:
        lines += ["", around]
    lines += ["", c["file"]]
    return Answer(plain="\n".join(lines))


def recheck(previous: dict, answer: Answer, new_citations: list[dict]) -> Answer:
    """Open with "I checked again.", and say so when the sources behind the answer changed
    completely, or one answer found something and the other didn't."""
    before = {c.get("file") for c in previous.get("citations") or []}
    after = {c.get("file") for c in new_citations}
    changed = bool(before) != bool(after) or bool(before and after and not before & after)
    head = f"{CHECKED} {CHANGED}" if changed else CHECKED
    if answer.nothing_found and answer.plain is None:
        answer.plain = NOTHING
    if answer.plain is not None:
        answer.plain = f"{head}\n{answer.plain}"
    else:
        answer.title = f"{head}\n{answer.title}" if answer.title else head
    return answer

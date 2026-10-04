"""Send each understood part where it belongs (spec: understand-first §2.2).

Questions go to intents, tellings and answers to "Who is …?" to tell.py (which saves them in
journal/told.md), and instructions to the action list. Labels ending in "->gap" mark what
Archie couldn't do or use; the usage log collects them."""

from __future__ import annotations

import re

from archie.ask.actions import ACTIONS, CANT_SEND, EMPTY, cant_do
from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import HANDLERS
from archie.ask.tell import answer_yes_no, tell
from archie.ask.understand import FACTS, Part
from archie.derive.audit import YES_NO

__all__ = ["EMPTY", "dispatch"]

UNCLEAR = "I'm not sure what you mean. Could you say it another way?"


def _who_is_subject(q: dict) -> str:
    m = re.match(r"Who is (.+?)\?", q.get("text", ""))
    return m.group(1) if m else ""


def _fact(part: Part) -> str:
    return part.fact if part.fact in FACTS else "person"


def dispatch(ctx: Ctx, part: Part, message: str, open_qs: list[dict], last: dict | None = None) -> tuple[str, Answer]:
    """(what handled the part, for the usage log; the reply)."""
    if part.kind == "question":
        name = part.intent if part.intent in HANDLERS else "search"
        label = name if name == part.intent else f"{part.intent}->search"
        return label, HANDLERS[name](ctx, part.resolved or part.text, {**EMPTY, **part.params})
    if part.kind == "tell":
        fact = _fact(part)
        return ("other->gap" if fact == "other" else f"tell:{fact}"), tell(ctx, fact, part.text, about=part.about)
    if part.kind == "answer":
        q = open_qs[part.question - 1]
        if q.get("kind") in YES_NO:
            return "clarify", answer_yes_no(ctx, part.text)
        fact, subject = _fact(part), _who_is_subject(q) or None
        label = "other->gap" if fact == "other" else f"answer:{fact}"
        return label, tell(ctx, fact, part.text, about=part.about or subject, subject=subject)
    if part.kind == "instruct":
        if part.action in ACTIONS:
            return part.action, ACTIONS[part.action](ctx, part, message, last)
        if part.action == "send":
            return "send->gap", Answer(plain=CANT_SEND)
        return f"{part.action or 'none'}->gap", cant_do(ctx, part)
    ask = (part.ask or "").strip()
    return "unclear", Answer(plain=ask if ask.endswith("?") and len(ask) <= 160 else UNCLEAR)

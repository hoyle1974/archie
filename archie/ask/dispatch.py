"""Send each understood part where it belongs (spec: understand-first §2.2).

Questions go to intents, tellings and answers to "Who is …?" to tell.py (which saves them in
journal/told.md), and instructions to the action list. Labels ending in "->gap" mark what
Archie couldn't do or use; the usage log collects them."""

from __future__ import annotations

import re

from archie.ask.actions import ACTIONS, CANT_SEND, EMPTY, answer_nudge, cant_do
from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import HANDLERS
from archie.ask.tell import answer_yes_no, tell
from archie.ask.understand import FACTS, Part
from archie.ask.which import ask_which, resolve
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
    if part.kind == "answer" and part.options:
        pending = (last or {}).get("pending")
        if pending and 1 <= part.options[0] <= len(pending.get("options") or []):
            return "which", resolve(ctx, pending, part.options[0] - 1)
        return "unclear", Answer(plain=UNCLEAR)
    if part.kind == "answer":
        q = open_qs[part.question - 1]
        if q.get("kind") == "waiting_nudge":
            return "answer:nudge", answer_nudge(ctx, q, part)
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
    if len(part.options) >= 2:
        qs = [open_qs[o - 1] for o in part.options]
        options = [{"label": _question_label(q), "id": q.get("id")} for q in qs]
        return "unclear", Answer(plain=ask_which([o["label"] for o in options]),
                                 pending={"kind": "question", "text": part.text, "fact": part.fact, "options": options})
    ask = (part.ask or "").strip()
    return "unclear", Answer(plain=ask if ask.endswith("?") and len(ask) <= 160 else UNCLEAR)


def _question_label(q: dict) -> str:
    """An open question as an option: who it asks about, or its first sentence."""
    text = q.get("text", "")
    nudge = re.match(r"Still waiting on (.+?) \(\d+ days?\)", text)
    return _who_is_subject(q) or (nudge.group(1) if nudge else f"“{text.split('?')[0].strip()}”")

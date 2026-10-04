"""Send each understood part where it belongs (spec: understand-first §2.2).

Tellings and answers to "Who is …?" go to tell.py, which saves them in journal/told.md.
Until the action list (step 3) exists, other instructions go to the intents that already
carry them out."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.followup import citation_number, show
from archie.ask.intents import HANDLERS
from archie.ask.tell import answer_yes_no, tell
from archie.ask.understand import FACTS, Part
from archie.derive.audit import YES_NO

EMPTY = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
CANT_SEND = "I can't send anything; I only read."
CANT_YET = "I can't do that yet."
UNCLEAR = "I'm not sure what you mean. Could you say it another way?"
WHICH = 'Which source? Say, for example, "show 2".'
_SHOW_N = re.compile(r"\[(\d+)\]|\b(?:show|open|source|citation|number)\s+(?:me\s+)?(?:the\s+)?"
                     r"(?:source\s+|citation\s+)?#?(\d+)\b(?!\s*(?:st|nd|rd|th)\b)", re.I)
ACTION_INTENT = {"loop_done": "loop_update", "loop_snooze": "loop_update", "loop_dismiss": "loop_update",
                 "loop_reopen": "loop_update", "meeting_type": "correct", "merge_names": "correct", "notes": "notes"}


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
        if part.action == "show_citation":
            m = _SHOW_N.search(part.text)
            n = citation_number(part.text) or (int(m.group(1) or m.group(2)) if m else None)
            return "show_citation", show(ctx, last, n) if n else Answer(plain=WHICH)
        if part.action in ("ignore", "unignore"):
            return part.action, tell(ctx, part.action, part.text, about=part.target or part.about)
        name = ACTION_INTENT.get(part.action or "")
        if name == "notes":  # the notes handler finds the note's start in the whole message
            return "notes", HANDLERS["notes"](ctx, message, {**EMPTY, **part.params})
        if name:
            return name, HANDLERS[name](ctx, part.text, dict(EMPTY))
        if part.action == "send":
            return "send", Answer(plain=CANT_SEND)
        return f"{part.action or 'none'}->cant", Answer(plain=CANT_YET)
    ask = (part.ask or "").strip()
    return "unclear", Answer(plain=ask if ask.endswith("?") and len(ask) <= 160 else UNCLEAR)

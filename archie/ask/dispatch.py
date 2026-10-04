"""Send each understood part where it belongs (spec: understand-first §2.2).

Until the told record (step 2) and the action list (step 3) exist, tellings go to
`remember` and instructions go to the intents that already carry them out."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.followup import citation_number, show
from archie.ask.intents import HANDLERS
from archie.ask.understand import Part
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


def dispatch(ctx: Ctx, part: Part, message: str, open_qs: list[dict], last: dict | None = None) -> tuple[str, Answer]:
    """(what handled the part, for the usage log; the reply)."""
    if part.kind == "question":
        name = part.intent if part.intent in HANDLERS else "search"
        label = name if name == part.intent else f"{part.intent}->search"
        return label, HANDLERS[name](ctx, part.resolved or part.text, {**EMPTY, **part.params})
    if part.kind == "tell":
        return "remember", HANDLERS["remember"](ctx, part.text, dict(EMPTY))
    if part.kind == "answer":
        q = open_qs[part.question - 1]
        if q.get("kind") in YES_NO:
            return "clarify", HANDLERS["clarify"](ctx, part.text, dict(EMPTY))
        subject = _who_is_subject(q)
        return "remember", HANDLERS["remember"](ctx, f"{subject}: {part.text}" if subject else part.text, dict(EMPTY))
    if part.kind == "instruct":
        if part.action == "show_citation":
            m = _SHOW_N.search(part.text)
            n = citation_number(part.text) or (int(m.group(1) or m.group(2)) if m else None)
            return "show_citation", show(ctx, last, n) if n else Answer(plain=WHICH)
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

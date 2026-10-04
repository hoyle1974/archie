""""Which one did you mean?" (spec: understand-first §5.1).

When more than one thing fits, code writes the question from the options and the answer
carries them as `pending`; the pipeline saves that in the conversation entry. The next
message (within the 30-minute window) answers it: by number, ordinal or a word only one
option has (matched here, no model), or as an `answer` part from the understanding call.
Then the original request runs on the chosen option."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx

_NUMBER = re.compile(r"^\s*(?:(?:number|no\.?|option)\s*)?#?(\d+)\s*[.!]?\s*$", re.I)
_ORDINAL = re.compile(r"^\s*(?:the\s+)?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)"
                      r"(?:\s+one)?\s*[.!]?\s*$", re.I)
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
             "fifth": 4, "5th": 4}
_FILLER = {"the", "a", "an", "one", "ones", "that", "this", "it", "her", "his", "their", "them", "she", "he",
           "they", "i", "mean", "meant", "of", "with", "about", "is", "was", "please", "s"}
_MAX_WORDS = 3


def _words(text: str) -> list[str]:
    return [re.sub(r"['’]s$", "", w) for w in re.findall(r"[\w'’-]+", text.lower())]


def ask_which(labels: list[str]) -> str:
    listed = " or ".join(labels) if len(labels) == 2 else f"{', '.join(labels[:-1])} or {labels[-1]}"
    return f"Which one: {listed}?"


def match(text: str, labels: list[str]) -> int | None:
    """The option a short reply picks (0-based), or None. Only a bare number, a bare ordinal,
    or up to three words that are all in exactly one option's label count."""
    m = _NUMBER.match(text or "")
    if m:
        n = int(m.group(1))
        return n - 1 if 1 <= n <= len(labels) else None
    m = _ORDINAL.match(text or "")
    if m:
        n = len(labels) - 1 if m.group(1).lower() == "last" else _ORDINALS[m.group(1).lower()]
        return n if n < len(labels) else None
    said = [w for w in _words(text or "") if w not in _FILLER]
    if not said or len(said) > _MAX_WORDS:
        return None
    owners = set()
    for w in said:
        having = {i for i, label in enumerate(labels) if w in _words(label)}
        if len(having) != 1:
            return None
        owners |= having
    return owners.pop() if len(owners) == 1 else None


def resolve(ctx: Ctx, pending: dict, index: int) -> Answer:
    """Run the request that was waiting on "which one?" for option `index`."""
    from archie.ask.actions import finish_loops
    from archie.derive.loops import load_loops

    chosen = pending["options"][index]
    if pending.get("kind") == "question":
        return _answer_question(ctx, pending, chosen["id"])
    lp = next((x for x in load_loops(ctx.home) if x.loop_id == chosen["id"]), None)
    if lp is None:
        return Answer(plain="I can't find that item anymore.")
    closed = lp.meta.get("status") in ("done", "dismissed")
    if pending["action"] == "reopen" and not closed:
        return Answer(plain="That one is already open.")
    if pending["action"] != "reopen" and closed:
        return Answer(plain="That one is already closed, so I left it alone.")
    return finish_loops(ctx, pending["action"], [lp], pending.get("until"), pending.get("reason"))


def _answer_question(ctx: Ctx, pending: dict, qid: str) -> Answer:
    from archie.ask.dispatch import dispatch
    from archie.ask.understand import Part
    from archie.derive.dedupe import open_questions

    open_qs = open_questions(ctx.home)
    number = next((i for i, q in enumerate(open_qs, 1) if q.get("id") == qid), None)
    if number is None:
        return Answer(plain="That question has already been answered.")
    part = Part(kind="answer", text=pending["text"], question=number, fact=pending.get("fact"))
    return dispatch(ctx, part, pending["text"], open_qs)[1]

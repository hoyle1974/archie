"""Classify a question into an intent with parameters (DESIGN §8 step 1).

The router selects a plan; it states no facts, so its output needs no citations.
"""

from __future__ import annotations

import re

from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Record, Shape

INTENT_HELP = {
    "agenda": "what's on the calendar for a day or range (\"what do I have tomorrow?\", \"what's my week like?\")",
    "brief": "prepare for one specific meeting (\"prep me for 2pm\", \"what's my next meeting about?\")",
    "who": "who someone is, history with them, or a group like \"my family\" (\"who is Priya?\")",
    "loops": "open items: owed, promised, waiting on (\"what do I owe people?\")",
    "loop_update": "mark an open item done/snoozed/not-a-loop (\"done with Sarah's question\")",
    "next": "what to work on next",
    "ledger": "accomplishments over a period (\"what did I get done this week?\")",
    "handover": "write a project handover",
    "notes": "the user is giving notes from a meeting",
    "catchup": "what happened while away",
    "remember": "the user tells you about people: relationships, roles, pronouns, other names "
                "(\"Goodspouse is my wife\", \"Acorn is my youngest\", \"Robert is the principal\")",
    "correct": "correct a meeting type or merge two names (\"that's a 1:1\", \"Alex R. is Alex Rivera\")",
    "help": "what Archie can do or how to use it",
    "search": "anything else: find information in the archive",
}

_PARAMS = ("people", "since", "until", "topic", "meeting", "text")
SHAPE = Shape(
    "route",
    fields=(F("intent", "choice", choices=tuple(INTENT_HELP)),
            F("people", "list", required=False, hint="names or emails mentioned"),
            F("since", required=False, hint="ISO date"), F("until", required=False, hint="ISO date"),
            F("topic", required=False), F("meeting", required=False),
            F("text", required=False, hint="for notes: the note text verbatim")),
    records=(Record("ALSO", "also", F("intent", "choice", choices=tuple(INTENT_HELP)),
                    (F("text", hint="the exact sentences of that part"),)),),
    nest=("params", _PARAMS),
    example="intent: loop_update\npeople: Ken\nsince: -\nuntil: -\ntopic: -\nmeeting: -\ntext: -\n"
            "ALSO remember\ntext: Sam is my neighbor.",
)

ACTIONS = ("loop_update", "remember", "correct", "notes", "clarify")


def split_parts(question: str, also: list[dict], main: str) -> list[tuple[str, str]]:
    """Extra parts of a mixed message: (intent, its words). Only actions, each intent once;
    if the model's words aren't really in the message, the part gets the whole message."""
    out, seen = [], {main}
    for part in also or []:
        intent, text = part.get("intent"), (part.get("text") or "").strip()
        if intent not in ACTIONS or intent in seen:
            continue
        seen.add(intent)
        squash = lambda x: re.sub(r"\s+", " ", x).strip()  # noqa: E731  (models collapse double spaces)
        out.append((intent, text if text and squash(text) in squash(question) else question))
    return out


QUICK = [
    (r"^(help|what can you do\??|how do i use (you|archie)\??)$", "help"),
    (r"^what (should|do) i (work on|do) (next|now)\??$|^what('s| is) next\??$", "next"),
    (r"^what (do i owe( people| anyone)?|am i waiting on|('s| is) open|are my open items)\??$", "loops"),
    (r"^what('s| is| do i have)( planned| going on| happening| on my calendar)?( for| on)? "
     r"(today|tomorrow|tonight|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\??$", "agenda"),
    (r"^what('s| is) (on )?my (calendar|schedule|agenda)( for)? ?(today|tomorrow)?\??$", "agenda"),
]


def quick_route(question: str) -> str | None:
    """Unambiguous questions with no parameters skip the model call (saves seconds)."""
    q = re.sub(r"\s+", " ", question.strip().lower())
    return next((intent for rx, intent in QUICK if re.match(rx, q)), None)


def route(ctx: Ctx, question: str) -> tuple[str, dict]:
    intent, params, _ = route_all(ctx, question)
    return intent, params


def route_all(ctx: Ctx, question: str) -> tuple[str, dict, list[tuple[str, str]]]:
    """The main intent and its parameters, plus any extra parts of a mixed message."""
    empty = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
    quick = quick_route(question)
    if quick:
        return quick, empty, []
    from archie.ask.intents.clarify import looks_like_answer
    from archie.derive.dedupe import open_questions

    if any(q["kind"] in ("same_person", "loop_done", "loop_stale") for q in open_questions(ctx.home)) \
            and looks_like_answer(question):
        return "clarify", empty, []
    local = ctx.now.astimezone()
    system = load_prompt("route", me_name=ctx.me.name or "the user", now=local.isoformat(timespec="minutes"),
                         weekday=local.strftime("%A"),
                         intents="\n".join(f"- {k}: {v}" for k, v in INTENT_HELP.items()))
    out = ctx.backend.complete(system, question, SHAPE, tier="fast")
    params = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
    params.update(out.get("params") or {})
    intent = out.get("intent", "search")
    return intent, params, split_parts(question, out.get("also") or [], intent)

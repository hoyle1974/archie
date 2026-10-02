"""Classify a question into an intent with parameters (DESIGN §8 step 1).

The router selects a plan; it states no facts, so its output needs no citations.
"""

from __future__ import annotations

import re

from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt

INTENT_HELP = {
    "brief": "prepare for a meeting (\"prep me for 2pm\", \"what's my next meeting about?\")",
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

_NULLABLE = {"type": ["string", "null"]}

SCHEMA = {
    "title": "route",
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENT_HELP)},
        "params": {
            "type": "object",
            "properties": {"people": {"type": "array", "items": {"type": "string"}}, "since": _NULLABLE,
                           "until": _NULLABLE, "topic": _NULLABLE, "meeting": _NULLABLE, "text": _NULLABLE},
            "required": ["people", "since", "until", "topic", "meeting", "text"],
            "additionalProperties": False,
        },
    },
    "required": ["intent", "params"],
    "additionalProperties": False,
}


QUICK = [
    (r"^(help|what can you do\??|how do i use (you|archie)\??)$", "help"),
    (r"^what (should|do) i (work on|do) (next|now)\??$|^what('s| is) next\??$", "next"),
    (r"^what (do i owe( people| anyone)?|am i waiting on|('s| is) open|are my open items)\??$", "loops"),
]


def quick_route(question: str) -> str | None:
    """Unambiguous questions with no parameters skip the model call (saves seconds)."""
    q = re.sub(r"\s+", " ", question.strip().lower())
    return next((intent for rx, intent in QUICK if re.match(rx, q)), None)


def route(ctx: Ctx, question: str) -> tuple[str, dict]:
    empty = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
    quick = quick_route(question)
    if quick:
        return quick, empty
    local = ctx.now.astimezone()
    system = load_prompt("route", me_name=ctx.me.name or "the user", now=local.isoformat(timespec="minutes"),
                         weekday=local.strftime("%A"),
                         intents="\n".join(f"- {k}: {v}" for k, v in INTENT_HELP.items()))
    out = ctx.backend.complete(system, question, SCHEMA, tier="fast")
    params = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
    params.update(out.get("params") or {})
    return out.get("intent", "search"), params

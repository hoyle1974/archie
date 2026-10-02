"""Classify a question into an intent with parameters (DESIGN §8 step 1).

The router selects a plan; it states no facts, so its output needs no citations.
"""

from __future__ import annotations

from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt

INTENT_HELP = {
    "brief": "prepare for a meeting (\"prep me for 2pm\", \"what's my next meeting about?\")",
    "who": "who someone is or history with them (\"who is Priya?\", \"history with Alex?\")",
    "loops": "open items: owed, promised, waiting on (\"what do I owe people?\")",
    "loop_update": "mark an open item done/snoozed/not-a-loop (\"done with Sarah's question\")",
    "next": "what to work on next",
    "ledger": "accomplishments over a period (\"what did I get done this week?\")",
    "handover": "write a project handover",
    "notes": "the user is giving notes from a meeting",
    "catchup": "what happened while away",
    "correct": "correct Archie (\"that's a 1:1\", \"Alex R. is Alex Rivera\")",
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


def route(ctx: Ctx, question: str) -> tuple[str, dict]:
    local = ctx.now.astimezone()
    system = load_prompt("route", me_name=ctx.me.name or "the user", now=local.isoformat(timespec="minutes"),
                         weekday=local.strftime("%A"),
                         intents="\n".join(f"- {k}: {v}" for k, v in INTENT_HELP.items()))
    out = ctx.backend.complete(system, question, SCHEMA, tier="fast")
    params = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
    params.update(out.get("params") or {})
    return out.get("intent", "search"), params

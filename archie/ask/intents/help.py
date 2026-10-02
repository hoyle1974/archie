"""`help`: what Archie can do, as example questions. Fixed text, no LLM."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent

HELP = """\
Just ask in plain English: archie ask "…" (or type in the Ask pane).

  Meetings      "prep me for my 2pm" · "what's my next meeting about?"
  People        "who is Priya?" · "what's my history with Alex?"
  Open items    "what do I owe people?" · "what am I waiting on?"
                "done with Sarah's question" · "snooze that till Monday"
  Focus         "what should I work on next?"
  Your record   "what did I get done this week?" · "what did I ship this quarter?"
  Notes         "notes from the design review: …"
  Anything else "who changed the auth config last week?"

Add --sources to see where each [n] came from."""


@intent("help")
def help_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    return Answer(plain=HELP)

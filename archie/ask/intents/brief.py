"""`brief`: prepare for a meeting (Vignette A)."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.briefings.build import build_briefing, pick_meeting, upcoming


@intent("brief")
def brief_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    meeting = pick_meeting(ctx, params.get("meeting") or params.get("topic"))
    if meeting is None:
        soon = upcoming(ctx)
        if not soon:
            return Answer(plain="You have no upcoming meetings in the next day and a half.")
        names = "\n".join(f"  • {m.meta.get('title')}" for m in soon[:6])
        return Answer(plain=f"Which meeting? Coming up:\n{names}\n(For your whole schedule, ask \"what do I have today?\")")
    return build_briefing(ctx, meeting).answer

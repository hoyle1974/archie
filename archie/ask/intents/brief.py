"""`brief`: prepare for a meeting (Vignette A), or for people with no meeting yet (Vignette V)."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.briefings.build import build_briefing, meeting_with, people_briefing, pick_meeting, resolve_people, upcoming
from archie.derive.people import PeopleDirectory

AHEAD_DAYS = 14


@intent("brief")
def brief_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    names = [n for n in params.get("people") or [] if n]
    if names:
        ids, said = resolve_people(PeopleDirectory.load(ctx.home), names)
        if ids:
            meeting = meeting_with(ctx, ids, AHEAD_DAYS)
            return build_briefing(ctx, meeting).answer if meeting else people_briefing(ctx, question, ids, said)
    text = params.get("meeting") or params.get("topic")
    meeting = pick_meeting(ctx, text) or pick_meeting(ctx, text, AHEAD_DAYS * 24)
    if meeting is None:
        soon = upcoming(ctx, AHEAD_DAYS * 24)
        if not soon:
            return Answer(plain="You have no meetings to prepare for in the next two weeks.")
        names = "\n".join(f"  • {m.meta.get('title')}" for m in soon[:6])
        return Answer(plain=f"Which meeting? Coming up:\n{names}\n(For your whole schedule, ask \"what do I have today?\")")
    return build_briefing(ctx, meeting).answer

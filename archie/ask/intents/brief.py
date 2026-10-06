"""`brief`: prepare for a meeting (Vignette A), or for people with no meeting yet (Vignette V)."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.briefings.build import build_briefing, meeting_with, people_briefing, pick_meeting, resolve_people, upcoming
from archie.derive.people import PeopleDirectory

AHEAD_DAYS = 14
NO_MEETINGS = "You have no meetings to prepare for in the next two weeks."


def _which_meeting(soon: list) -> str:
    names = "\n".join(f"  • {m.meta.get('title')}" for m in soon[:6])
    return f"Which meeting? Coming up:\n{names}\n(For your whole schedule, ask \"what do I have today?\")"


@intent("brief")
def brief_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    names = [n for n in params.get("people") or [] if n]
    if names:
        ids, said = resolve_people(PeopleDirectory.load(ctx.home), names)
        if ids:
            meeting = meeting_with(ctx, ids, AHEAD_DAYS)
            return build_briefing(ctx, meeting).answer if meeting else people_briefing(ctx, question, ids, said)
        # nobody named is known: the next meeting isn't about them, so none is picked
        soon = upcoming(ctx, AHEAD_DAYS * 24)
        rest = _which_meeting(soon) if soon else NO_MEETINGS
        unknown = [n for n in names if f"I don't know anyone called {n}." in said]  # not "more than one"
        return Answer(plain="\n".join([*said, rest]),
                      dead_end=f"no file on anyone called {' or '.join(unknown)}" if unknown else None)
    text = params.get("meeting") or params.get("topic")
    meeting = pick_meeting(ctx, text) or pick_meeting(ctx, text, AHEAD_DAYS * 24)
    if meeting is None:
        soon = upcoming(ctx, AHEAD_DAYS * 24)
        if not soon:
            return Answer(plain=NO_MEETINGS, dead_end="no meeting matched")
        return Answer(plain=_which_meeting(soon))
    return build_briefing(ctx, meeting).answer

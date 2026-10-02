"""`next`: what to work on now (Vignette D). Entirely code-computed: free time from the
calendar, then open loops ranked (DESIGN §6.5) with a boost for people you meet today.
Waiting-on items old enough to chase are listed separately as nudges."""

from __future__ import annotations

from datetime import datetime

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.intents.loops import _claim, _line
from archie.briefings.schedule import todays
from archie.derive.loops import load_loops, rank
from archie.llm.verify import Claim

NUDGE_AFTER_DAYS = 3


def _free_time(ctx: Ctx) -> tuple[str, set[str]]:
    meetings = todays(ctx)
    people = {p for m in meetings for p in m.meta.get("attendees") or []}
    upcoming = [m for m in meetings if datetime.fromisoformat(m.meta["start"]) > ctx.now]
    if not upcoming:
        return "Your calendar is clear for the rest of the day.", people
    m = upcoming[0]
    start = datetime.fromisoformat(m.meta["start"])
    minutes = int((start - ctx.now).total_seconds() // 60)
    span = f"{minutes} minutes" if minutes < 120 else f"{minutes // 60} hours"
    return f"You have {span} before {m.meta.get('title')} ({start.astimezone():%-I:%M %p}).", people


@intent("next")
def next_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    free, people = _free_time(ctx)
    ranked = rank(load_loops(ctx.home), ctx.now, ctx.config, upcoming_people=people)
    todo = [r for r in ranked if r.loop.meta["kind"] != "waiting_on"]
    nudges = [r for r in ranked if r.loop.meta["kind"] == "waiting_on"
              and (ctx.now - datetime.fromisoformat(r.loop.meta["created_at"])).days >= NUDGE_AFTER_DAYS]
    if not todo and not nudges:
        return Answer(plain=f"{free} You have nothing open. Good time for deep work.")
    summary = [Claim(free, [])]
    if todo:
        top = todo[0].loop.meta
        summary.append(_claim(ctx, todo[0], f"Best use: {top.get('summary')} ({top.get('counterpart_name')})."))
    answer = Answer(summary=summary)
    if todo:
        answer.sections.append(Section("Do next", items=[_claim(ctx, r, f"{i}. {_line(r)}")
                                                         for i, r in enumerate(todo[:5], 1)]))
    if nudges:
        answer.sections.append(Section("Nudge", items=[_claim(ctx, r, _line(r)) for r in nudges[:3]]))
    answer.notes.append("Order: due soonest and overdue first, then people you're meeting today, then oldest.")
    return answer

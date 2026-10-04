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
from archie.derive.audit import _about
from archie.derive.loops import load_loops, rank
from archie.llm.verify import Claim


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
    ranked = [r for r in rank(load_loops(ctx.home), ctx.now, ctx.config, upcoming_people=people) if not r.stale]
    todo = [r for r in ranked if r.loop.meta["kind"] != "waiting_on"]
    waiting = [r for r in ranked if r.loop.meta["kind"] == "waiting_on"]
    replied = [r for r in waiting if r.loop.meta.get("replied")]  # your turn again
    after = int(ctx.config.get("nudges", {}).get("after_days", 3))
    nudges = [r for r in waiting if not r.loop.meta.get("replied")
              and (ctx.now - datetime.fromisoformat(r.loop.meta["created_at"])).days >= after]
    from archie.store.files import read_raw

    in_progress = []
    for p in sorted((ctx.home / "sources/jira").glob("*.json")):
        d = read_raw(p)
        if d.get("assignee_me") and d.get("status_category") == "indeterminate" and not d.get("deleted"):
            in_progress.append(f"{d['key']} {d['summary']} ({d['status']})")
    if not todo and not nudges and not in_progress and not replied:
        if waiting:  # "nothing open" would be wrong: you're waiting on someone
            m = waiting[0].loop.meta
            more = f" (and {len(waiting) - 1} more)" if len(waiting) > 1 else ""
            return Answer(summary=[Claim(free, []), _claim(ctx, waiting[0], (
                f"Nothing for you to do. You're waiting on {m.get('counterpart_name') or m.get('counterpart')} "
                f"about {_about(m)}{more}."))])
        return Answer(plain=f"{free} You have nothing open. Good time for deep work.")
    summary = [Claim(free, [])]
    if not todo and in_progress:
        summary.append(Claim(f"Best use: keep going on {in_progress[0]}.", []))
    if todo:
        top = todo[0].loop.meta
        summary.append(_claim(ctx, todo[0], f"Best use: {top.get('summary')} ({top.get('counterpart_name')})."))
    elif replied:
        top = replied[0].loop.meta
        summary.append(_claim(ctx, replied[0], f"{top.get('counterpart_name')} replied about {_about(top)}; "
                                               "your turn."))
    answer = Answer(summary=summary)
    if replied:
        answer.sections.append(Section("They replied", items=[_claim(ctx, r, _line(r)) for r in replied[:5]]))
    if todo:
        answer.sections.append(Section("Do next", items=[_claim(ctx, r, _line(r)) for r in todo[:5]]))
    if in_progress:
        answer.sections.append(Section("In progress", lines=in_progress))
    if nudges:
        answer.sections.append(Section("Nudge", items=[_claim(ctx, r, _line(r)) for r in nudges[:3]]))
    answer.notes.append("Order: due soonest and overdue first, then people you're meeting today, then oldest.")
    return answer

"""`agenda`: what's on the calendar for a day or a range ("what do I have tomorrow?",
"what's Friday look like?"). Computed from the calendar mirror, no LLM: all-day events
first, then timed events (meetings show who's in them). Declined and cancelled events
are left out; the same event on two calendars is shown once. Plans the user told Archie
(journal/plans.md) show on their days, in the user's words (Vignette X)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.derive.people import PeopleDirectory
from archie.store.files import read_raw

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def window_from_words(question: str, today: date) -> tuple[date, date] | None:
    q = question.lower()
    if "tomorrow" in q:
        return today + timedelta(days=1), today + timedelta(days=1)
    if "today" in q or "tonight" in q:
        return today, today
    if "this week" in q:
        return today, today + timedelta(days=6 - today.weekday())
    if "next week" in q:
        start = today + timedelta(days=7 - today.weekday())
        return start, start + timedelta(days=6)
    if "weekend" in q:
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        return sat, sat + timedelta(days=1)
    for i, name in enumerate(DAYS):
        if re.search(rf"\b{name}\b", q):
            d = today + timedelta(days=(i - today.weekday()) % 7)
            return d, d
    return None


LATE_HOUR = 22  # from 10 PM, "today" with nothing left also shows tomorrow


def _over(e: dict, now: datetime) -> bool:
    """A timed event that has already ended (all-day events last the whole day)."""
    if e.get("all_day"):
        return e["_day"] < now.astimezone().date()
    return datetime.fromisoformat(e.get("end") or e["start"]) <= now


def _parse(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def events_between(ctx: Ctx, start: date, end: date) -> list[dict]:
    seen, out = set(), []
    for p in sorted((ctx.home / "sources/calendar").glob("*.json")):
        d = read_raw(p)
        if d.get("deleted") or d.get("status") == "cancelled":
            continue
        if any(a.get("self") and a.get("response") == "declined" for a in d.get("attendees", [])):
            continue
        if d.get("all_day"):
            first = date.fromisoformat(d["start"][:10])
            last = date.fromisoformat(d["end"][:10]) - timedelta(days=1) if d.get("end") else first
            days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        else:
            days = [datetime.fromisoformat(d["start"]).astimezone().date()]
        key = (d.get("title"), d.get("start"))
        if key in seen:
            continue
        seen.add(key)
        for day in days:
            if start <= day <= end:
                out.append({**d, "_day": day})
    return sorted(out, key=lambda e: (e["_day"], not e.get("all_day"), e["start"]))


def _plan(p) -> str:
    return f"“{p.text}” ({p.said:%b} {p.said.day})"


@intent("agenda")
def agenda_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    today = ctx.now.astimezone().date()
    window = window_from_words(question, today)
    if params.get("since") or params.get("until"):
        start = _parse(params.get("since")) or today
        window = (start, _parse(params.get("until")) or start)
    start, end = window or (today, today)
    events = events_between(ctx, start, end)
    if (start, end) == (today, today) and ctx.now.astimezone().hour >= LATE_HOUR \
            and not any(not e.get("all_day") and not _over(e, ctx.now) for e in events):
        end = today + timedelta(days=1)  # late with nothing left today: you mean tomorrow too
        events = events_between(ctx, start, end)
    from archie.ask import plans

    directory = PeopleDirectory.load(ctx.home)
    told = plans.between(ctx.home, start, end)
    lines = []
    longer = [p for p in told if p.start != p.end]  # "next week": said once, not on every day
    if longer:
        lines += ["Plans you told me for these days:", *(f"  • {_plan(p)}" for p in longer), ""]
    for i in range((end - start).days + 1):
        day = start + timedelta(days=i)
        lines.append(f"{day:%A}, {day:%b} {day.day}")
        lines += [f"  You said: {_plan(p)}" for p in told if p.start == p.end == day]
        todays = [e for e in events if e["_day"] == day]
        if not todays:
            lines.append("  Nothing on your calendar.")
        for e in todays:
            others = [a for a in e.get("attendees", []) if not a.get("self") and not ctx.me.is_me(a.get("email", ""))]
            names = [directory.name(directory.by_email(a["email"])) if directory.by_email(a["email"])
                     else (a.get("name") or a["email"]) for a in others]
            who = f" · with {', '.join(names[:4])}" + (f" +{len(names) - 4}" if len(names) > 4 else "") if names else ""
            when = "All day" if e.get("all_day") else f"{datetime.fromisoformat(e['start']).astimezone():%-I:%M %p}"
            over = " (over)" if day == today and not e.get("all_day") and _over(e, ctx.now) else ""
            lines.append(f"  {when}  {e.get('title')}{who}{over}")
        if i < (end - start).days:
            lines.append("")
    return Answer(plain="\n".join(lines))

"""Plans the user tells Archie ("Monday is a company holiday", "I'll meet Workpersontwo next week";
Vignette X). Each is kept in journal/plans.md, one line, with the days code worked out from
the user's words (`dates.days_in`; the model never gives a date) and who it's with. The user
can edit the file. Agenda shows a plan on its days, and `brief` uses a planned meeting that
isn't on the calendar yet. A plan with no date is kept but shown on no day."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from archie.ask.context import Ctx
from archie.store.files import atomic_write
from archie.store.home import Home

FILE = "journal/plans.md"
HEAD = ("# Plans you told Archie\n\nThings you said will happen, with the days Archie worked out from your "
        "words. You can edit this file.\n\n")
LINE = re.compile(r'^- (?:(\d{4}-\d\d-\d\d)(?: to (\d{4}-\d\d-\d\d))?|no date) · "(.+)" · said (\d{4}-\d\d-\d\d)'
                  r'(?: · with (.+))?$')
PREP_DAYS = 14  # a planned meeting this far ahead (or said this recently, with no date) can be prepped


@dataclass
class Plan:
    start: date | None
    end: date | None
    text: str
    said: date
    people: list[str] = field(default_factory=list)


def load(home: Home) -> list[Plan]:
    path = home / FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line.strip())
        if not m:
            continue
        try:
            start = date.fromisoformat(m[1]) if m[1] else None
            end = date.fromisoformat(m[2]) if m[2] else start
            said = date.fromisoformat(m[4])
        except ValueError:
            continue
        people = [p.strip() for p in (m[5] or "").split(",") if p.strip()]
        out.append(Plan(start, end, m[3], said, people))
    return out


def _line(p: Plan) -> str:
    days = "no date" if p.start is None else p.start.isoformat() + (f" to {p.end.isoformat()}" if p.end != p.start else "")
    with_ = f" · with {', '.join(p.people)}" if p.people else ""
    return f'- {days} · "{p.text}" · said {p.said.isoformat()}{with_}\n'


def _short(d: date) -> str:
    return f"{d:%a}, {d:%b} {d.day}"


def save(ctx: Ctx, said: str, people: list[str]) -> tuple[Plan, str]:
    """Save a plan; (the plan, the reply)."""
    from archie.derive.dates import days_in

    now = ctx.now.astimezone()
    text = " ".join(said.split()).replace('"', "”")
    days = days_in(text, now)
    plan = Plan(days[0] if days else None, days[1] if days else None, text, now.date(), list(people))
    path = ctx.home / FILE
    old = path.read_text(encoding="utf-8") if path.exists() else HEAD
    atomic_write(path, (old if old.endswith("\n") else old + "\n") + _line(plan))
    words = plan.text.rstrip(" ,;:")
    quoted = f"“{words}”" + ("" if words.endswith((".", "!", "?")) else ".")
    if plan.start is None:
        return plan, f"Saved: {quoted} I couldn't tell which day, so it won't show in your agenda."
    if plan.start == plan.end:
        return plan, f"Saved for {_short(plan.start)}: {quoted} I'll show it in your agenda that day."
    return plan, f"Saved for {_short(plan.start)} to {_short(plan.end)}: {quoted} I'll show it in your agenda then."


def result(plan: Plan) -> str:
    """What journal/told.md records the telling did."""
    if plan.start is None:
        return "plan, no date"
    return f"plan for {plan.start.isoformat()}" + (f" to {plan.end.isoformat()}" if plan.end != plan.start else "")


def between(home: Home, start: date, end: date) -> list[Plan]:
    """Plans with days that overlap start..end, in the order told."""
    return [p for p in load(home) if p.start and p.start <= end and p.end >= start]


def for_prep(ctx: Ctx) -> Plan | None:
    """The plan most recently told with people in it that's still ahead: its days end today or
    later and start within two weeks, or it has no date and was said in the last two weeks."""
    today = ctx.now.astimezone().date()
    ahead = today + timedelta(days=PREP_DAYS)
    fits = [p for p in load(ctx.home) if p.people and (
        (p.start and p.end >= today and p.start <= ahead) or (p.start is None and p.said >= today - timedelta(days=PREP_DAYS)))]
    return fits[-1] if fits else None


def said_line(plan: Plan) -> str:
    return f"You said on {plan.said:%b} {plan.said.day}: “{plan.text}”"

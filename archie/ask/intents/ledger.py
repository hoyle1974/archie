"""`ledger`: what the user got done in a window (Vignettes E, K). Code-computed counts and
lists, each item cited to the exact source chunk. Also writes the weekly journal."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

from archie.activity import KIND_WORDS, Item, my_activity
from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.render import render
from archie.index.chunk import short_date
from archie.llm.verify import Citation, Claim
from archie.store.fence import set_fence
from archie.store.files import Note, read_note, write_note

LISTED = ("pr_merged", "pr_opened", "commit", "review_given", "issue_done", "transition", "doc_edited")
NOUNS = {"commit": ("commit", "commits"), "pr_merged": ("PR merged", "PRs merged"),
         "pr_opened": ("PR opened", "PRs opened"), "review_given": ("review", "reviews"),
         "issue_done": ("issue closed", "issues closed"), "transition": ("issue moved", "issues moved"),
         "doc_edited": ("doc edited", "docs edited"), "email_sent": ("email sent", "emails sent"),
         "meeting": ("meeting", "meetings")}


def _window(ctx: Ctx, params: dict) -> tuple[datetime, datetime]:
    tz = ctx.now.astimezone().tzinfo
    today = ctx.now.astimezone().date()

    def parse(s: str | None, default: date) -> date:
        try:
            return date.fromisoformat((s or "")[:10])
        except ValueError:
            return default

    start = parse(params.get("since"), today - timedelta(days=today.weekday()))
    end = parse(params.get("until"), today)
    return datetime.combine(start, time.min, tz), min(datetime.combine(end, time.max, tz), ctx.now)


def _claim(ctx: Ctx, item: Item) -> Claim:
    label = ctx.index.label_of(item.path, item.chunk)
    return Claim(f"{item.title} ({short_date(item.when)})", [Citation(0, item.path, item.chunk, item.quote, label)])


def _counts(items: list[Item]) -> str:
    c = Counter(i.kind for i in items)
    parts = [f"{c[k]} {NOUNS[k][0] if c[k] == 1 else NOUNS[k][1]}" for k in NOUNS if c[k]]
    return ", ".join(parts) if parts else "nothing recorded"


def ledger_answer(ctx: Ctx, start: datetime, end: datetime) -> Answer:
    items = my_activity(ctx, start, end)
    span = f"{short_date(start.isoformat())} – {short_date(end.isoformat())}"
    answer = Answer(summary=[Claim(f"{span}: {_counts(items)}.", [])])
    listed = [i for i in items if i.kind in LISTED]
    if (end - start).days > 31:
        for project in sorted({i.project for i in listed}):
            mine = [i for i in listed if i.project == project]
            answer.sections.append(Section(f"{project} ({_counts(mine)})", items=[_claim(ctx, i) for i in mine[-15:]]))
    else:
        for kind in LISTED:
            mine = [i for i in listed if i.kind == kind]
            if mine:
                answer.sections.append(Section(KIND_WORDS[kind], items=[_claim(ctx, i) for i in mine]))
    if not items:
        answer.notes.append("Nothing in your archive for that window. Sources only go back to when each was connected.")
    return answer


@intent("ledger")
def ledger_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    start, end = _window(ctx, params)
    return ledger_answer(ctx, start, end)


def write_week_journal(ctx: Ctx) -> Path:
    """journal/weekly/<YYYY>-W<ww>.md: this week's ledger inside the fence; the rest is the user's."""
    local = ctx.now.astimezone()
    monday = local.date() - timedelta(days=local.weekday())
    start = datetime.combine(monday, time.min, local.tzinfo)
    year, week, _ = monday.isocalendar()
    path = ctx.home / f"journal/weekly/{year}-W{week:02d}.md"
    note = read_note(path) if path.exists() else Note(meta={"week": f"{year}-W{week:02d}",
                                                           "start": monday.isoformat()}, body="## My notes\n\n")
    note.meta["updated"] = ctx.now.isoformat()
    note.body = set_fence(note.body, render(ledger_answer(ctx, start, ctx.now), sources=True) + "\n")
    write_note(path, note)
    return path

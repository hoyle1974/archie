"""Things the user tells Archie (spec: understand-first §3).

Every telling is saved word for word in journal/told.md, then applied where it fits:
facts about a person (the remember code), ignoring or un-ignoring a sender, or nothing yet.
Replies are written by code from what was applied. The user's words are taken as said and
never checked against the archive."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.clarify import clarify
from archie.ask.context import Ctx
from archie.ask.remember import remember_people
from archie.ask.render import render
from archie.derive.ignore import addresses_for, describe, ignored, on_list, set_ignored
from archie.derive.people import PeopleDirectory
from archie.store.files import atomic_write

TOLD = "journal/told.md"
HEAD = "# What you told Archie\n\nArchie adds a line each time you tell it something. You can edit this file.\n\n"
SAVED_ONLY = "saved only"
OTHER = "Saved. I don't use that for anything yet."


def save_told(ctx: Ctx, text: str, result: str) -> None:
    path = ctx.home / TOLD
    old = path.read_text(encoding="utf-8") if path.exists() else HEAD
    if not old.endswith("\n"):
        old += "\n"
    said = " ".join(text.split())
    atomic_write(path, f"{old}- {ctx.now.astimezone():%Y-%m-%d} · \"{said}\" → {result}\n")


def _person(ctx: Ctx, said: str) -> tuple[Answer, str]:
    lines = remember_people(ctx, said)
    if not lines:
        return Answer(plain="Saved. I couldn't tell who that's about, so I haven't added it to anyone's notes."), SAVED_ONLY
    return (Answer(plain="Got it. I'll remember:\n" + "\n".join(f"  • {x}" for x in lines)),
            "remembered: " + "; ".join(lines))


def _ignore(ctx: Ctx, on: bool, about: str | None, text: str) -> tuple[Answer, str]:
    directory = PeopleDirectory.load(ctx.home)
    addresses, which = addresses_for(directory, about, text)
    if which:
        return Answer(plain=f"Which one: {' or '.join(which)}? Say their email address to be sure."), SAVED_ONLY
    if on:
        mine = [a for a in addresses if any(on_list(m, [a]) for m in ctx.me.emails)]
        addresses = [a for a in addresses if a not in mine]
        if mine and not addresses:
            domain = next((a for a in mine if a.startswith("@")), None)
            return (Answer(plain=f"I won't ignore {domain}, because your own address is there." if domain
                           else "I won't ignore your own address."), SAVED_ONLY)
    if not addresses:
        verb = "ignored" if on else "stopped ignoring"
        return (Answer(plain=f"I couldn't tell which sender you mean, so I haven't {verb} anyone. "
                             "Try their email address."), SAVED_ONLY)
    who, short = describe(directory, addresses)
    if not on:
        listed = ignored(ctx.config)
        exact = [a for a in addresses if a in listed]
        if not exact:
            domains = [x for x in listed if x.startswith("@") and any(on_list(a, [x]) for a in addresses)]
            if domains:
                return (Answer(plain=f"You told me to ignore everything from {domains[0]}, which includes {who}.\n"
                                     f"Say \"stop ignoring {domains[0]}\" to undo that."), SAVED_ONLY)
            return Answer(plain=f"I wasn't ignoring {who}."), SAVED_ONLY
        set_ignored(ctx, exact, on=False)
        return Answer(plain=f"OK, I'm no longer ignoring {who}."), f"no longer ignoring {', '.join(exact)}"
    closed = set_ignored(ctx, addresses, on=True)
    reply = f"Got it. I'll ignore {who} from now on.\nSay \"stop ignoring {short}\" to undo."
    if closed:
        reply += f"\nI also dismissed {closed} open item{'' if closed == 1 else 's'} from them."
    return Answer(plain=reply), f"ignoring {', '.join(addresses)}"


def tell(ctx: Ctx, fact: str, text: str, about: str | None = None, subject: str | None = None) -> Answer:
    """Apply one telling. `subject` is who an answered "Who is …?" question was about."""
    result = SAVED_ONLY
    try:
        if fact in ("ignore", "unignore"):
            answer, result = _ignore(ctx, fact == "ignore", about or subject, text)
        elif fact == "person":
            answer, result = _person(ctx, f"{subject}: {text}" if subject else text)
        else:
            answer = Answer(plain=OTHER)
        return answer
    finally:
        save_told(ctx, text, result)


def answer_yes_no(ctx: Ctx, text: str) -> Answer:
    """A reply to Archie's yes/no questions, saved with what it did."""
    result = SAVED_ONLY
    try:
        answer = clarify(ctx, text)
        first = render(answer).strip().splitlines()
        result = first[0] if first else SAVED_ONLY
        return answer
    finally:
        save_told(ctx, text, result)

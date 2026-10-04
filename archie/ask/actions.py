"""The things Archie can do when told to (spec: understand-first §4).

Each action is fn(ctx, part, message, last) -> Answer, and its reply says what the code
actually did. The understanding call picks the action; for open items the fast model only
picks which ones."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.correct import correct
from archie.ask.followup import citation_number, show
from archie.ask.intents import HANDLERS
from archie.ask.tell import save_told, tell
from archie.ask.understand import Part
from archie.derive.loops import Loop, _history, load_loops, rank, save_loop
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Shape

EMPTY = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
CANT_SEND = "I can't send anything; I only read."
WISH = "can't do this yet"
WHICH = 'Which source? Say, for example, "show 2".'
UNTIL_WHEN = 'Until when? Say e.g. "snooze that till Monday".'
_SHOW_N = re.compile(r"\[(\d+)\]|\b(?:show|open|source|citation|number)\s+(?:me\s+)?(?:the\s+)?"
                     r"(?:source\s+|citation\s+)?#?(\d+)\b(?!\s*(?:st|nd|rd|th)\b)", re.IGNORECASE)

UPDATE_SHAPE = Shape("loop_update",
                     fields=(F("loops", "int_list", required=False, hint="item numbers"),
                             F("until", required=False, hint="ISO date"), F("reason", required=False)),
                     example="loops: 2; 3\nuntil: 2026-10-05\nreason: -")
WANTS = {"done": "mark them finished", "snooze": "snooze them (hide them until a date)",
         "dismiss": "dismiss them (they were never real items)", "reopen": "reopen them"}


def when(day: str, today: date) -> str:
    d = date.fromisoformat(day)
    gap = (d - today).days
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    if 1 < gap <= 6:
        return f"{d:%A}"
    return f"{d:%a}, {d:%b} {d.day}"


def _iso(day: str | None) -> str | None:
    try:
        return date.fromisoformat(str(day).strip()).isoformat() if day else None
    except ValueError:
        return None


def _lower_first(text: str) -> str:
    """"Review the patch" → "review the patch", but "IEP form" stays."""
    return text[0].lower() + text[1:] if text[:1].isupper() and not text[1:2].isupper() else text


def _label(loop: Loop) -> str:
    m = loop.meta
    what = _lower_first(str(m.get("summary") or "").strip().rstrip("."))
    return f"{m.get('counterpart_name') or m.get('counterpart')}, {what}"


def _apply(ctx: Ctx, loop: Loop, action: str, until: str | None, reason: str | None) -> None:
    m, today = loop.meta, ctx.now.astimezone().date().isoformat()
    if action == "done":
        m["status"], m["closed_by"] = "done", {"user": f"said done {today}"}
    elif action == "snooze":
        m["status"], m["snoozed_until"] = "snoozed", until
    elif action == "dismiss":
        m["status"], m["dismissed_reason"] = "dismissed", reason
    elif action == "reopen":
        m["status"], m["closed_by"], m["snoozed_until"] = "open", None, None
    _history(loop, f"{today} you said: {action}" + (f" until {until}" if until else "") + (f" ({reason})" if reason else ""))
    save_loop(ctx.home, loop)


def update_loops(ctx: Ctx, said: str, action: str, until: str | None = None) -> Answer:
    """Mark open items done, snoozed or dismissed, or reopen closed ones."""
    all_loops = load_loops(ctx.home)
    active = [r.loop for r in rank(all_loops, ctx.now, ctx.config)]
    choices = [lp for lp in all_loops if lp not in active][-10:] if action == "reopen" else active
    if not choices:
        return Answer(plain="You have nothing closed to reopen." if action == "reopen"
                      else "You have no open items to update.")
    listing = "\n".join(f"{i}. {lp.meta.get('counterpart_name')}: {lp.meta.get('summary')}"
                        for i, lp in enumerate(choices, 1))
    local = ctx.now.astimezone()
    system = load_prompt("loop_update", me_name=ctx.me.name or "the user", today=local.date().isoformat(),
                         weekday=local.strftime("%A"), wants=WANTS[action])
    out = ctx.backend.complete(system, f"Items:\n{listing}\n\nThey said: {said}", UPDATE_SHAPE, tier="fast")
    picked = [choices[n - 1] for n in out.get("loops") or [] if 1 <= n <= len(choices)]
    if not picked:
        top = "\n".join(f"  • {lp.meta.get('counterpart_name')}: {lp.meta.get('summary')}" for lp in choices[:8])
        return Answer(plain=f"I couldn't tell which item you meant. Your {'closed' if action == 'reopen' else 'open'} "
                            f"items:\n{top}")
    until = _iso(until) or _iso(out.get("until"))
    if action == "snooze" and not until:
        return Answer(plain=UNTIL_WHEN)
    for lp in picked:
        _apply(ctx, lp, action, until if action == "snooze" else None, out.get("reason"))
    verb = {"done": "Marked done", "dismiss": "Dismissed", "reopen": "Reopened",
            "snooze": f"Snoozed until {when(until, local.date())}" if until else ""}[action]
    text = f"{verb}: " + "; ".join(_label(lp) for lp in picked) + "."
    if action == "dismiss":
        muted = _maybe_mute(ctx, picked)
        if muted:
            text += (f"\nYou've dismissed items from {', '.join(muted)} twice, so I won't track their mail anymore "
                     f"(added to loops.mute in config.yaml; delete it there to undo).")
    return Answer(plain=text)


def _maybe_mute(ctx: Ctx, picked: list[Loop]) -> list[str]:
    """A repeated dismissal becomes an explicit, visible rule (DESIGN §6.3), never hidden learning."""
    import yaml

    from archie.derive.people import EMAIL, PeopleDirectory

    directory = PeopleDirectory.load(ctx.home)
    dismissed = [lp for lp in load_loops(ctx.home) if lp.meta.get("status") == "dismissed"]
    cfg_path = ctx.home.config_file
    cfg = (yaml.safe_load(cfg_path.read_text()) or {}) if cfg_path.exists() else {}
    mute = list((cfg.get("loops") or {}).get("mute") or [])
    added = []
    for lp in picked:
        cp = lp.meta.get("counterpart")
        if sum(1 for d in dismissed if d.meta.get("counterpart") == cp) < 2:
            continue
        emails = [cp] if EMAIL.match(str(cp)) else [a for a in directory.identifiers(cp) if EMAIL.match(a)]
        for e in emails:
            if e not in mute:
                mute.append(e)
                added.append(lp.meta.get("counterpart_name") or e)
    if added:
        cfg.setdefault("loops", {})["mute"] = mute
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
        ctx.config["loops"]["mute"] = mute
    return sorted(set(added))


def _loop(action: str) -> Callable[[Ctx, Part, str, dict | None], Answer]:
    return lambda ctx, part, message, last: update_loops(ctx, part.text, action, part.params.get("until"))


def _show(ctx: Ctx, part: Part, message: str, last: dict | None) -> Answer:
    m = _SHOW_N.search(part.text)
    n = citation_number(part.text) or (int(m.group(1) or m.group(2)) if m else None)
    return show(ctx, last, n) if n else Answer(plain=WHICH)


def _ignore(on: bool) -> Callable[[Ctx, Part, str, dict | None], Answer]:
    name = "ignore" if on else "unignore"
    return lambda ctx, part, message, last: tell(ctx, name, part.text, about=part.target or part.about)


def cant_do(ctx: Ctx, part: Part) -> Answer:
    """Something Archie can't do yet: say so in the user's terms and save it as a wish."""
    wanted = (part.wanted or "").strip().rstrip(".")
    if wanted and "\n" not in wanted and len(wanted.split()) <= 12:
        head = f"I can't {_lower_first(' '.join(wanted.split()))} yet."
    else:
        head = f"I can't do “{' '.join(part.text.split()).rstrip('.')}” yet."
    save_told(ctx, part.text, WISH)
    return Answer(plain=f"{head} I've saved that you want it.")


def _saved(text: str) -> str:
    return f"I saved that {_lower_first(' '.join(text.split()).rstrip('.!'))}."


def compose_cant(handled: list[tuple[Part, str, Answer]]) -> list[tuple[Part, Answer]]:
    """When a message has something Archie can't do, tellings are said first ("I saved that
    …"), and one-line replies become one line."""
    if not any(p.kind == "instruct" and label.endswith("->gap") for p, label, _ in handled):
        return [(p, a) for p, _, a in handled]
    tells = [(p, Answer(plain=_saved(p.text)) if label == "other->gap" else a)
             for p, label, a in handled if p.kind == "tell"]
    ordered = tells + [(p, a) for p, _, a in handled if p.kind != "tell"]
    if all(a.plain is not None and "\n" not in a.plain for _, a in ordered):
        return [(ordered[0][0], Answer(plain=" ".join(a.plain for _, a in ordered)))]
    return ordered


ACTIONS: dict[str, Callable[[Ctx, Part, str, dict | None], Answer]] = {
    "loop_done": _loop("done"), "loop_snooze": _loop("snooze"), "loop_dismiss": _loop("dismiss"),
    "loop_reopen": _loop("reopen"),
    "meeting_type": lambda ctx, part, message, last: correct(ctx, part.text),
    "merge_names": lambda ctx, part, message, last: correct(ctx, part.text),
    # the notes handler finds the note's start in the whole message
    "notes": lambda ctx, part, message, last: HANDLERS["notes"](ctx, message, {**EMPTY, **part.params}),
    "ignore": _ignore(True), "unignore": _ignore(False),
    "show_citation": _show,
}

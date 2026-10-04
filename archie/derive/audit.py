"""The audit: after each sync, look for confusion in new data and turn it into a few
clarifying questions (shown in the Today pane, answered in plain English).

Kinds:
- same_person: two dossiers that are probably one person (see dedupe.py)
- loop_done:   Archie thinks an item is finished but isn't sure ("Did you finish …?")
- loop_stale:  an item more than a week past due ("Do you still need to …?")
- waiting_nudge: you've waited `nudges.after_days` or more on someone with no reply in the
               thread ("Still waiting on …. Want to follow up?"); clears itself when they
               reply or the item closes, and comes back only after a snooze ends
- who_is:      someone you correspond with known only by an address ("Who is …?");
               answered by telling Archie about them; it clears itself once it knows.
               Never asked about ignored senders
At most MAX_OPEN questions are open at once, most important first, so it never floods.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from archie.ask.context import Ctx
from archie.derive.dedupe import _who, find_duplicates, load_questions, save_questions
from archie.derive.ignore import ignored_person
from archie.derive.loops import Loop, _history, load_loops, rank, save_loop, their_reply
from archie.derive.people import EMAIL, PeopleDirectory

MAX_OPEN = 5
PRIORITY = {"same_person": 0, "loop_done": 1, "loop_stale": 2, "waiting_nudge": 3, "who_is": 4}
YES_NO = ("same_person", "loop_done", "loop_stale")
_ARTICLES = ("the", "a", "an", "my", "your", "their", "our")
# Loop summaries are usually imperative ("Review the patch"); "the review the patch" reads badly.
_VERBS = frozenset(re.findall(r"\w+", """add answer approve arrange ask attend book bring buy call cancel check
clarify complete confirm decide deliver discuss draft drop email file find finish fix follow forward get give help
install investigate let look make meet merge move order organize pay pick plan prepare provide read register remind
renew reply resolve respond return review schedule send set share sign submit take talk tell test text troubleshoot
update upload write"""))


def _qid(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}|{key}".encode()).hexdigest()[:8]


def _waiting_days(ctx: Ctx, lp: Loop) -> int | None:
    """Whole days the user has waited on an open `waiting_on` item with no reply in its
    thread, or None if it shouldn't be nudged (closed, snoozed, too young, answered)."""
    m = lp.meta
    today = ctx.now.astimezone().date()
    snooze_over = m.get("status") == "snoozed" and str(m.get("snoozed_until") or "9999") <= today.isoformat()
    if m.get("kind") != "waiting_on" or not (m.get("status") == "open" or snooze_over):
        return None
    try:
        created = datetime.fromisoformat(str(m.get("created_at")))
    except ValueError:
        return None
    days = (today - created.astimezone().date()).days
    if days < int(ctx.config.get("nudges", {}).get("after_days", 3)):
        return None
    if not m.get("thread") or not (ctx.home / f"sources/gmail/{m.get('thread')}.json").exists():
        return None  # no thread to check for a reply
    return None if their_reply(ctx.home, m) else days


def _about(m: dict) -> str:
    """"the earbud pairing" for a short noun phrase, the summary in quotes otherwise."""
    what = str(m.get("summary") or "").strip().rstrip(".")
    words = what.split()
    if not words or len(words) > 4 or words[0].lower() in _VERBS:
        return f"“{what}”"
    names = {w.lower() for w in str(m.get("counterpart_name") or "").split()}
    if words[0][:1].isupper() and not words[0][1:2].isupper() and words[0].lower().split("'")[0] not in names:
        what = what[0].lower() + what[1:]
    return what if words[0].lower() in _ARTICLES else f"the {what}"


def _candidates(ctx: Ctx) -> list[dict]:
    out = []
    now = ctx.now.isoformat()
    for lp in load_loops(ctx.home):
        m = lp.meta
        if m.get("status") == "maybe_done":
            label = (m.get("closed_by") or {}).get("file", "")
            out.append({"id": _qid("loop_done", lp.loop_id), "kind": "loop_done", "loop": lp.loop_id,
                        "text": f"Did you finish: {m.get('summary')} ({m.get('counterpart_name')})?"
                                + (f" I saw related activity in {label.split('/')[1]}." if label.count("/") > 1 else ""),
                        "status": "open", "asked_at": now})
    for r in rank(load_loops(ctx.home), ctx.now, ctx.config):
        if r.stale:
            m = r.loop.meta
            out.append({"id": _qid("loop_stale", r.loop.loop_id), "kind": "loop_stale", "loop": r.loop.loop_id,
                        "text": f"Do you still need to: {m.get('summary')} ({m.get('counterpart_name')})? "
                                f"It was due {m.get('due')}.", "status": "open", "asked_at": now})
    for lp in load_loops(ctx.home):
        days = _waiting_days(ctx, lp)
        if days is not None:
            m = lp.meta
            out.append({"id": _qid("waiting_nudge", f"{lp.loop_id}|{m.get('snoozed_until') or ''}"),
                        "kind": "waiting_nudge", "loop": lp.loop_id,
                        "text": f"Still waiting on {m.get('counterpart_name') or m.get('counterpart')} about "
                                f"{_about(m)} ({days} day{'' if days == 1 else 's'}). Want to follow up?",
                        "status": "open", "asked_at": now})
    d = PeopleDirectory.load(ctx.home)
    for e, m in d.meta.items():
        name = str(m.get("name") or "")
        unnamed = "@" in name or (" " not in name.strip() and not m.get("relationship") and not m.get("role"))
        if unnamed and m.get("last_interaction") and m.get("status") != "merged" and not ignored_person(d, e, ctx.config):
            email = next((a for a in d.identifiers(e) if EMAIL.match(a)), name)
            out.append({"id": _qid("who_is", e), "kind": "who_is", "person": e,
                        "text": f"Who is {email}? Tell me, e.g. \"{email} is my plumber\".", "status": "open",
                        "asked_at": now})
    return out


def _still_relevant(ctx: Ctx, q: dict) -> bool:
    if q["kind"] in ("loop_done", "loop_stale"):
        lp = next((x for x in load_loops(ctx.home) if x.loop_id == q.get("loop")), None)
        if lp is None:
            return False
        if q["kind"] == "loop_done":
            return lp.meta.get("status") == "maybe_done"
        return any(r.stale and r.loop.loop_id == lp.loop_id for r in rank([lp], ctx.now, ctx.config))
    if q["kind"] == "waiting_nudge":
        lp = next((x for x in load_loops(ctx.home) if x.loop_id == q.get("loop")), None)
        return lp is not None and _waiting_days(ctx, lp) is not None
    if q["kind"] == "who_is":
        d = PeopleDirectory.load(ctx.home)
        m = d.meta.get(q.get("person"), {})
        name = str(m.get("name") or "")
        return (bool(m) and not ignored_person(d, q["person"], ctx.config) and not m.get("relationship")
                and not m.get("role") and ("@" in name or " " not in name.strip()))
    return True


def resolve_answered(ctx: Ctx) -> list[dict]:
    """Mark questions answered some other way (item closed by hand, person described) as
    resolved. Cheap and model-free: runs after every answer and before Today is drawn."""
    qs = load_questions(ctx.home)
    changed = False
    for q in qs:
        if q["status"] == "open" and q["kind"] in ("loop_done", "loop_stale", "waiting_nudge", "who_is") \
                and not _still_relevant(ctx, q):
            q["status"] = "resolved"
            changed = True
    if changed:
        save_questions(ctx.home, qs)
    return qs


def audit(ctx: Ctx) -> None:
    find_duplicates(ctx)
    qs = resolve_answered(ctx)
    known = {q["id"] for q in qs}
    new = [c for c in _candidates(ctx) if c["id"] not in known]
    open_now = [q for q in qs if q["status"] == "open" and q["kind"] != "notice"]
    room = max(0, MAX_OPEN - len(open_now))
    qs += sorted(new, key=lambda c: PRIORITY[c["kind"]])[:room]
    save_questions(ctx.home, qs)


def answer(ctx: Ctx, q: dict, yes: bool) -> str:
    """Apply a yes/no answer to an open question."""
    from archie.derive.dedupe import answer_same_person

    if q["kind"] == "same_person":
        return answer_same_person(ctx, q, yes)
    qs = load_questions(ctx.home)
    for x in qs:
        if x["id"] == q["id"]:
            x.update(status="answered", answer="yes" if yes else "no", answered_at=ctx.now.isoformat())
    save_questions(ctx.home, qs)
    lp = next((x for x in load_loops(ctx.home) if x.loop_id == q.get("loop")), None)
    if lp is None:
        return "That item is gone already."
    m, today = lp.meta, ctx.now.date().isoformat()
    if q["kind"] == "loop_done":
        if yes:
            m["status"] = "done"
            _history(lp, f"{today} you confirmed it's done")
            msg = f"Marked done: {m.get('summary')}."
        else:
            m["status"], m["closed_by"] = "open", None
            _history(lp, f"{today} you said it's not done yet")
            msg = f"Kept open: {m.get('summary')}."
    else:  # loop_stale
        if yes:
            m["due"] = None
            _history(lp, f"{today} you said it's still needed")
            msg = f"Kept: {m.get('summary')} (no due date now)."
        else:
            m["status"], m["closed_by"] = "done", {"user": f"said no longer needed {today}"}
            _history(lp, f"{today} you said it's no longer needed")
            msg = f"Closed: {m.get('summary')}."
    save_loop(ctx.home, lp)
    return msg

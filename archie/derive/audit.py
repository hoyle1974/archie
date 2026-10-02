"""The audit: after each sync, look for confusion in new data and turn it into a few
clarifying questions (shown in the Today pane, answered in plain English).

Kinds:
- same_person: two dossiers that are probably one person (see dedupe.py)
- loop_done:   Archie thinks an item is finished but isn't sure ("Did you finish …?")
- loop_stale:  an item more than a week past due ("Do you still need to …?")
- who_is:      someone you correspond with known only by an address ("Who is …?");
               answered by telling Archie about them; it clears itself once it knows
At most MAX_OPEN questions are open at once, most important first, so it never floods.
"""

from __future__ import annotations

import hashlib

from archie.ask.context import Ctx
from archie.derive.dedupe import _who, find_duplicates, load_questions, save_questions
from archie.derive.loops import _history, load_loops, rank, save_loop
from archie.derive.people import EMAIL, PeopleDirectory

MAX_OPEN = 5
PRIORITY = {"same_person": 0, "loop_done": 1, "loop_stale": 2, "who_is": 3}
YES_NO = ("same_person", "loop_done", "loop_stale")


def _qid(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}|{key}".encode()).hexdigest()[:8]


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
    d = PeopleDirectory.load(ctx.home)
    for e, m in d.meta.items():
        name = str(m.get("name") or "")
        unnamed = "@" in name or (" " not in name.strip() and not m.get("relationship") and not m.get("role"))
        if unnamed and m.get("last_interaction") and m.get("status") != "merged":
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
    if q["kind"] == "who_is":
        m = PeopleDirectory.load(ctx.home).meta.get(q.get("person"), {})
        name = str(m.get("name") or "")
        return bool(m) and not m.get("relationship") and not m.get("role") and ("@" in name or " " not in name.strip())
    return True


def audit(ctx: Ctx) -> None:
    find_duplicates(ctx)
    qs = load_questions(ctx.home)
    for q in qs:  # questions answered some other way clear themselves
        if q["status"] == "open" and q["kind"] in ("loop_done", "loop_stale", "who_is") and not _still_relevant(ctx, q):
            q["status"] = "resolved"
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

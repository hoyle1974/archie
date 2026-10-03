"""`loops` and `loop_update` (Vignette C): list open items ranked by code, and let the
user close, snooze, dismiss or reopen them in plain English."""

from __future__ import annotations

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.derive.loops import Loop, Ranked, _history, load_loops, rank, save_loop
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Shape
from archie.llm.verify import Citation, Claim

def _claim(ctx: Ctx, r: Ranked, text: str) -> Claim:
    src = (r.loop.meta.get("sources") or [{}])[0]
    cites = []
    if src.get("file"):
        cites.append(Citation(0, src["file"], src.get("chunk", "c0"), src.get("quote", ""),
                              ctx.index.label_of(src["file"], src.get("chunk", "c0"))))
    return Claim(text, cites)


def _line(r: Ranked) -> str:
    m = r.loop.meta
    who = m.get("counterpart_name") or m.get("counterpart")
    kind = m.get("kind")
    head = f"{who}: {m.get('summary')}" if kind != "waiting_on" else f"(waiting on) {who}: {m.get('summary')}"
    return f"{head} · {', '.join(r.why)}" if r.why else head


def _filter(question: str, params: dict, ranked: list[Ranked]) -> list[Ranked]:
    q = question.lower()
    if "waiting" in q:
        ranked = [r for r in ranked if r.loop.meta["kind"] == "waiting_on"]
    elif any(w in q for w in ("owe", "promised", "i need to", "do i have to")):
        ranked = [r for r in ranked if r.loop.meta["kind"] != "waiting_on"]
    names = [n.lower() for n in params.get("people") or []]
    if names:
        ranked = [r for r in ranked if any(n in str(r.loop.meta.get("counterpart_name", "")).lower()
                                           or n in str(r.loop.meta.get("counterpart", "")) for n in names)]
    return ranked


@intent("loops")
def loops_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    everything = _filter(question, params, rank(load_loops(ctx.home), ctx.now, ctx.config))
    ranked = [r for r in everything if not r.stale]
    stale = [r for r in everything if r.stale]
    if not everything:
        return Answer(plain="You have nothing open that matches. Nice.")
    if not ranked:
        answer = Answer(summary=[Claim("Nothing current is open.", [])])
        answer.sections.append(Section("Maybe already done? (say \"done with …\")",
                                       items=[_claim(ctx, r, _line(r)) for r in stale[:10]]))
        return answer
    top = ranked[0]
    count = f"You have {len(ranked)} open item{'s' if len(ranked) != 1 else ''}."
    m = top.loop.meta
    reason = f" ({', '.join(top.why)})" if top.why else ""
    link = "waiting on" if m["kind"] == "waiting_on" else "for"
    who = m.get("counterpart_name") or ""
    tail = "" if who and who.lower() in str(m.get("summary", "")).lower() else f", {link} {who}"
    urgent = f"Most urgent: {m.get('summary')}{tail}{reason}."
    answer = Answer(summary=[Claim(count, []), _claim(ctx, top, urgent)])
    answer.sections.append(Section("Open items", items=[_claim(ctx, r, _line(r)) for r in ranked[:15]]))
    if len(ranked) > 15:
        answer.notes.append(f"…and {len(ranked) - 15} more.")
    if stale:
        answer.sections.append(Section("Maybe already done? (say \"done with …\")",
                                       items=[_claim(ctx, r, _line(r)) for r in stale[:10]]))
    return answer


UPDATE_SHAPE = Shape("loop_update",
                     fields=(F("action", "choice", choices=("done", "snooze", "dismiss", "reopen")),
                             F("loops", "int_list", required=False, hint="item numbers"),
                             F("until", required=False, hint="ISO date"), F("reason", required=False)),
                     example="action: snooze\nloops: 2; 3\nuntil: 2026-10-05\nreason: -")


def _apply(ctx: Ctx, loop: Loop, action: str, until: str | None, reason: str | None) -> str:
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
    return f"{m.get('summary')} ({m.get('counterpart_name')})"


@intent("loop_update")
def loop_update_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    all_loops = load_loops(ctx.home)
    active = [r.loop for r in rank(all_loops, ctx.now, ctx.config)]
    recent_closed = [lp for lp in all_loops if lp not in active][-10:]
    choices = active + recent_closed
    if not choices:
        return Answer(plain="You have no open items to update.")
    listing = "\n".join(f"{i}. [{lp.meta.get('status')}] {lp.meta.get('counterpart_name')}: {lp.meta.get('summary')}"
                        for i, lp in enumerate(choices, 1))
    local = ctx.now.astimezone()
    system = load_prompt("loop_update", me_name=ctx.me.name or "the user", today=local.date().isoformat(),
                         weekday=local.strftime("%A"))
    out = ctx.backend.complete(system, f"Items:\n{listing}\n\nThey said: {question}", UPDATE_SHAPE, tier="fast")
    picked = [choices[n - 1] for n in out.get("loops") or [] if 1 <= n <= len(choices)]
    if not picked:
        top = "\n".join(f"  • {lp.meta.get('counterpart_name')}: {lp.meta.get('summary')}" for lp in active[:8])
        return Answer(plain=f"I couldn't tell which item you meant. Your open items:\n{top}")
    action = out["action"]
    if action == "snooze" and not out.get("until"):
        return Answer(plain="Until when? Say e.g. \"snooze that till Monday\".")
    done = [_apply(ctx, lp, action, out.get("until"), out.get("reason")) for lp in picked]
    verb = {"done": "Marked done", "snooze": f"Snoozed until {out.get('until')}", "dismiss": "Dismissed",
            "reopen": "Reopened"}[action]
    text = f"{verb}: " + "; ".join(done)
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

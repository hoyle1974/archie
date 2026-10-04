"""`loops` (Vignette C): list open items ranked by code. Closing, snoozing, dismissing and
reopening them are actions (archie/ask/actions.py)."""

from __future__ import annotations

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.derive.loops import Ranked, load_loops, rank
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

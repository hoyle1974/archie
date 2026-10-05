"""ask(): the single entry point behind `archie ask` and the TUI's Ask pane.

A message is first understood (understand.py) with the recent conversation and Archie's
open questions in view, then each part is sent where it belongs (dispatch.py). Every
finished exchange goes to state/conversation.jsonl, which follow-ups read, and to
logs/usage.jsonl (local only, gitignored): what was said, how each part was handled, how
long it took, whether anything was found, and the answer shown (with source paths), so
answers can be triaged later."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import NamedTuple

from archie.ask import conversation
from archie.ask.actions import compose_cant
from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.dispatch import EMPTY, dispatch
from archie.ask.followup import citation_number, is_recheck, recheck, show
from archie.ask.intents import HANDLERS, load_all
from archie.ask.router import quick_route
from archie.ask.understand import Part, understand
from archie.ask.which import match, resolve


class Reply(NamedTuple):
    answer: Answer
    resolved: str | None
    citations: list[dict] | None  # None: take them from the answer


def _log(ctx: Ctx, entry: dict) -> None:
    try:
        path = ctx.home / "logs/usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break an answer


def _cited(a: Answer) -> bool:
    return a.plain is None and not a.nothing_found and bool(a.summary or a.sections)


def combine(handled: list[tuple[Part, Answer]]) -> Answer:
    """One reply for a mixed message. Cited replies are merged into one answer, so a single
    numbering covers every [n] and every source; plain replies are joined as text."""
    from archie.ask.render import render

    first = handled[0][1]
    if len(handled) == 1:
        return first
    if not any(_cited(a) for _, a in handled):
        texts = [render(a) for _, a in handled[1:]]
        if first.plain is not None:
            first.plain = "\n\n".join([first.plain, *texts])
        else:
            first.notes += texts
        return first
    out = first if _cited(first) else Answer(title=render(first))
    for part, a in handled[1:]:
        if _cited(a):
            heading = " ".join(part.text.split())
            out.sections.append(Section(heading[:77] + "…" if len(heading) > 80 else heading,
                                        items=list(a.summary), lines=[a.title] if a.title else []))
            out.sections += a.sections
            out.dropped += a.dropped
            out.notes += a.notes
        else:
            out.notes.append(render(a))
    return out


def _question_of(last: dict | None) -> str | None:
    """The question the last exchange answered, if it was only questions ("show N" keeps the
    one before it). "really?" re-asks this; anything else (a telling, notes) is never redone."""
    kinds = (last or {}).get("kinds") or []
    if kinds and all(k == "question" for k in kinds):
        return last.get("resolved") or last.get("said")
    return last.get("resolved") if kinds == ["show"] else None


def _respond(ctx: Ctx, question: str, entry: dict) -> Reply:
    from archie.ask.clarify import looks_like_answer
    from archie.ask.render import citations_of
    from archie.ask.tell import answer_yes_no
    from archie.derive.audit import YES_NO
    from archie.derive.dedupe import open_questions

    quick = quick_route(question)
    if quick:
        entry.update(quick=True, intent=quick, parts=[{"kind": "question", "handler": quick}])
        return Reply(HANDLERS[quick](ctx, question, dict(EMPTY)), None, None)
    recent = conversation.recent(ctx.home, ctx.now)
    last = recent[-1] if recent else None
    kept = (last or {}).get("citations") or []
    n = citation_number(question)
    if n is not None:
        entry.update(quick=True, intent="show_citation", parts=[{"kind": "show", "handler": "show_citation"}])
        return Reply(show(ctx, last, n), _question_of(last), kept)
    pending = (last or {}).get("pending")
    chosen = match(question, [o["label"] for o in pending["options"]]) if pending else None
    if chosen is not None:
        entry.update(quick=True, intent="which", parts=[{"kind": "answer", "handler": "which"}])
        return Reply(resolve(ctx, pending, chosen), None, None)
    again = _question_of(last)
    if is_recheck(question) and again and not is_recheck(again):
        entry["recheck"] = again
        reply = _respond(ctx, again, entry)
        new = citations_of(reply.answer)
        return Reply(recheck(last, reply.answer, new), again, new)
    open_qs = open_questions(ctx.home)
    nudging = any(q["kind"] == "waiting_nudge" for q in open_qs)  # "yes, I'll follow up" answers a nudge
    if not pending and not nudging and any(q["kind"] in YES_NO for q in open_qs) and looks_like_answer(question):
        entry.update(intent="clarify", parts=[{"kind": "answer", "handler": "clarify"}])
        return Reply(answer_yes_no(ctx, question), None, None)
    parts = understand(ctx, question, recent, open_qs, pending)
    handled = [dispatch(ctx, p, question, open_qs, last) for p in parts]
    entry["intent"] = handled[0][0]
    entry["parts"] = [{"kind": p.kind, "handler": label, "people": p.params.get("people") or [],
                       "topic": p.params.get("topic")} for p, (label, _) in zip(parts, handled)]
    gaps = [p.text for p, (label, _) in zip(parts, handled) if label.endswith("->gap")]
    if gaps:
        entry["gaps"] = gaps
    resolved = next((p.resolved for p in parts if p.kind == "question" and p.resolved), None)
    waiting = next((a.pending for _, a in handled if a.pending), None)
    answer = combine(compose_cant(ctx, [(p, label, a) for p, (label, a) in zip(parts, handled)]))
    answer.pending = waiting
    if all(label == "show_citation" for label, _ in handled):
        return Reply(answer, _question_of(last), kept)
    return Reply(answer, resolved, None)


def ask(ctx: Ctx, question: str) -> Answer:
    from archie.ask.render import citations_of, render
    from archie.derive.audit import resolve_answered

    load_all()
    started = time.monotonic()
    entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "question": question, "quick": False}
    try:
        reply = _respond(ctx, question, entry)
        answer = reply.answer
        answer.at = ctx.now  # stored UTC; render(stamp=True) shows it in local time
        resolve_answered(ctx)  # e.g. closing an item clears "still needed?" about it
        entry.update(nothing_found=answer.nothing_found, dropped=answer.dropped,
                     claims=len(answer.summary) + sum(len(s.items) for s in answer.sections),
                     sources=[f"{it.path}#{it.chunk_id}" for it in answer.packet.items],
                     answer=render(answer, sources=True, paths=True)[:6000])
        parts = entry.get("parts", [])
        kinds = ["show"] if parts and all(p["handler"] == "show_citation" for p in parts) else [p["kind"] for p in parts]
        try:
            conversation.append(ctx.home, {
                "ts": ctx.now.isoformat(), "said": question, "resolved": reply.resolved,
                "kinds": kinds, "summary": render(answer)[:800],
                "shown": render(answer, sources=True, stamp=True),
                "citations": citations_of(answer) if reply.citations is None else reply.citations,
                "pending": answer.pending})
        except OSError:
            pass  # a lost exchange only weakens follow-ups; the answer still shows
        return answer
    except Exception as exc:
        entry["error"] = str(exc)[:200]
        raise
    finally:
        entry["ms"] = int((time.monotonic() - started) * 1000)
        _log(ctx, entry)

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
from datetime import datetime, timezone
from typing import NamedTuple

from archie.ask import conversation
from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.dispatch import EMPTY, dispatch
from archie.ask.intents import HANDLERS, load_all
from archie.ask.router import quick_route
from archie.ask.understand import understand


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


def combine(first: Answer, more: list[Answer]) -> Answer:
    """One reply for a mixed message: plain replies are joined; otherwise they become notes."""
    from archie.ask.render import render

    texts = [render(a) for a in more]
    if first.plain is not None:
        first.plain = "\n\n".join([first.plain, *texts])
    else:
        first.notes += texts
    return first


def _respond(ctx: Ctx, question: str, entry: dict) -> Reply:
    from archie.ask.intents.clarify import looks_like_answer
    from archie.derive.audit import YES_NO
    from archie.derive.dedupe import open_questions

    quick = quick_route(question)
    if quick:
        entry.update(quick=True, intent=quick)
        return Reply(HANDLERS[quick](ctx, question, dict(EMPTY)), None, None)
    open_qs = open_questions(ctx.home)
    if any(q["kind"] in YES_NO for q in open_qs) and looks_like_answer(question):
        entry["intent"] = "clarify"
        return Reply(HANDLERS["clarify"](ctx, question, dict(EMPTY)), None, None)
    recent = conversation.recent(ctx.home, ctx.now)
    parts = understand(ctx, question, recent, open_qs)
    last = recent[-1] if recent else None
    handled = [dispatch(ctx, p, question, open_qs, last) for p in parts]
    entry["intent"] = handled[0][0]
    entry["parts"] = [{"kind": p.kind, "handler": label} for p, (label, _) in zip(parts, handled)]
    resolved = next((p.resolved for p in parts if p.kind == "question" and p.resolved), None)
    return Reply(combine(handled[0][1], [a for _, a in handled[1:]]), resolved, None)


def ask(ctx: Ctx, question: str) -> Answer:
    from archie.ask.render import citations_of, render
    from archie.derive.audit import resolve_answered

    load_all()
    started = time.monotonic()
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question, "quick": False}
    try:
        reply = _respond(ctx, question, entry)
        answer = reply.answer
        resolve_answered(ctx)  # e.g. closing an item clears "still needed?" about it
        entry.update(nothing_found=answer.nothing_found, dropped=answer.dropped,
                     claims=len(answer.summary) + sum(len(s.items) for s in answer.sections),
                     answer=render(answer, sources=True, paths=True)[:6000])
        conversation.append(ctx.home, {
            "ts": ctx.now.isoformat(), "said": question, "resolved": reply.resolved,
            "summary": render(answer)[:800],
            "citations": citations_of(answer) if reply.citations is None else reply.citations})
        return answer
    except Exception as exc:
        entry["error"] = str(exc)[:200]
        raise
    finally:
        entry["ms"] = int((time.monotonic() - started) * 1000)
        _log(ctx, entry)

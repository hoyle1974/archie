"""ask(): the single entry point behind `archie ask` and the TUI's Ask pane.

Every question is appended to logs/usage.jsonl (local only, gitignored): what was asked,
how it was routed, how long it took, whether anything was found, and the answer shown
(with source paths), so answers can be triaged later. It's the record the
next round of improvements should come from."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import HANDLERS, load_all
from archie.ask.router import quick_route, route_all


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


def ask(ctx: Ctx, question: str) -> Answer:
    load_all()
    started = time.monotonic()
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question,
             "quick": quick_route(question) is not None}
    try:
        intent, params, extra = route_all(ctx, question)
        entry["intent"] = intent if intent in HANDLERS else f"{intent}->search"
        handler = HANDLERS.get(intent) or HANDLERS["search"]
        answer = handler(ctx, question, params)
        if extra:  # a mixed message: run each other part with its own words
            entry["also"] = [i for i, _ in extra]
            empty = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
            more = [HANDLERS[i](ctx, text, dict(empty)) for i, text in extra if i in HANDLERS]
            answer = combine(answer, more)
        from archie.ask.render import render

        entry.update(nothing_found=answer.nothing_found, dropped=answer.dropped,
                     claims=len(answer.summary) + sum(len(s.items) for s in answer.sections),
                     answer=render(answer, sources=True, paths=True)[:6000])
        return answer
    except Exception as exc:
        entry["error"] = str(exc)[:200]
        raise
    finally:
        entry["ms"] = int((time.monotonic() - started) * 1000)
        _log(ctx, entry)

"""Did the answer help? (spec: dig-deeper §1.2)

One fast-tier call sees what the user said, how it was understood, and the answer as it
would be shown, and says whether it helps; if not, one line on what's missing, which starts
the dig (dig.py). It states no facts about sources, so it needs no citations."""

from __future__ import annotations

from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Shape

SHAPE = Shape("answer_check", fields=(
    F("helpful", "bool"),
    F("missing", required=False, hint="what the user wanted that the answer doesn't give")),
    example="helpful: no\nmissing: prep for a meeting with Workpersontwo; the answer only says the calendar is empty")
MISSING = "the answer didn't give what the user asked for"


def enabled(ctx: Ctx) -> bool:
    return bool(((ctx.config.get("ask") or {}).get("dig") or {}).get("enabled"))


def answer_check(ctx: Ctx, message: str, question: str, shown: str, earlier: str = "") -> str | None:
    """None when the answer helps; otherwise what it misses, in a line."""
    from archie.ask.synthesize import now_line

    user = "\n\n".join(filter(None, [
        f"Now: {now_line(ctx)}",
        f"Earlier in the conversation, Archie said: {earlier}" if earlier else "",
        f"The user said: {message}" + (f"\nUnderstood as: {question}" if question != message else ""),
        f"Archie's answer:\n{shown}"]))
    out = ctx.backend.complete(load_prompt("answer_check", me_name=ctx.me.name or "the user"), user, SHAPE,
                               tier="fast")
    if out.get("helpful"):
        return None
    return (out.get("missing") or "").strip() or MISSING

"""The Feed pane: the next meeting's briefing, then the top open items."""

from __future__ import annotations

from archie.ask.context import Ctx
from archie.briefings.build import _path
from archie.briefings.schedule import todays
from archie.derive.loops import load_loops, rank
from archie.store.files import read_note


def build_feed(ctx: Ctx) -> str:
    parts = []
    meetings = todays(ctx)
    if meetings:
        m = meetings[0]
        path = ctx.home / _path(m)
        body = read_note(path).body.strip() if path.exists() else "(briefing not built yet)"
        parts.append(f"Next: {body}")
        if len(meetings) > 1:
            later = ", ".join(x.meta.get("title") for x in meetings[1:4])
            parts.append(f"Later today: {later}")
    else:
        parts.append("No more meetings today.")
    ranked = rank(load_loops(ctx.home), ctx.now, ctx.config)
    if ranked:
        lines = [f"  • {r.loop.meta.get('counterpart_name')}: {r.loop.meta.get('summary')}"
                 + (f" ({', '.join(r.why)})" if r.why else "") for r in ranked[:3]]
        more = f"\n  …{len(ranked) - 3} more: ask \"what do I owe people?\"" if len(ranked) > 3 else ""
        parts.append("Open items\n" + "\n".join(lines) + more)
    return "\n\n".join(parts)

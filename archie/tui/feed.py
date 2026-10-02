"""The Feed pane: what matters right now. Grows with briefings and open loops."""

from __future__ import annotations

from archie.ask.context import Ctx


def build_feed(ctx: Ctx) -> str:
    counts = ctx.index.counts()
    return f"Nothing to show yet.\n\n{counts['files']} files in your archive."

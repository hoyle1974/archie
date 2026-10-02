"""ask(): the single entry point behind `archie ask` and the TUI's Ask pane."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import HANDLERS, load_all
from archie.ask.router import route


def ask(ctx: Ctx, question: str) -> Answer:
    load_all()
    intent, params = route(ctx, question)
    handler = HANDLERS.get(intent) or HANDLERS["search"]
    return handler(ctx, question, params)

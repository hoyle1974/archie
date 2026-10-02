"""Intent handlers: fn(ctx, question, params) -> Answer. Unbuilt intents fall back to search."""

from __future__ import annotations

from typing import Callable

from archie.ask.answer import Answer
from archie.ask.context import Ctx

Handler = Callable[[Ctx, str, dict], Answer]
HANDLERS: dict[str, Handler] = {}


def intent(name: str):
    def register(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn

    return register


def load_all() -> None:
    from archie.ask.intents import (brief, catchup, clarify, correct, handover, help, ledger, loops, next,  # noqa: F401
                                    notes, remember, search, who)

"""Shared test helpers: a temp Archie home with a hash-embedder index and a fake LLM."""

from __future__ import annotations

from datetime import datetime, timezone

from archie.ask.context import Ctx
from archie.config import Me, load_config
from archie.index.db import Index
from archie.index.embed import HashEmbedder
from archie.llm.backend import FakeBackend
from archie.store.home import init_home

NOW = datetime(2026, 10, 1, 9, 10, tzinfo=timezone.utc)

TEST = Me(name="Test Testerson", legal_name="Harold Test Testerson III", aliases=["Test", "Test Testerson"],
          emails=["test.testerson@example.com", "test@acme.example"], github="ttesterson")


def make_ctx(tmp_path, backend=None, now=NOW, dig=False) -> Ctx:
    """`dig`: check answers and dig further (dig.py). Off by default: canned backends script
    every call, and the check would be one more."""
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    cfg["ask"]["dig"]["enabled"] = dig
    import copy

    return Ctx(home=home, config=cfg, me=copy.deepcopy(TEST), index=Index(home, HashEmbedder()),
               backend=backend or FakeBackend([]), now=now)


def by_schema(**handlers):
    """FakeBackend reply fn that dispatches on the shape's name."""

    def reply(system, user, shape, tier):
        fn = handlers[shape.name]
        return fn(system, user, shape, tier) if callable(fn) else fn

    return reply


PART_FIELDS = {"text": "", "resolved": None, "intent": None, "people": [], "since": None, "until": None,
               "topic": None, "meeting": None, "fact": None, "about": None, "question": None, "action": None,
               "target": None, "wanted": None, "options": [], "ask": None, "notes": None, "mine": None}


def part(kind: str, **fields) -> dict:
    """One part as the understanding call's parsed reply has it. An empty `text` means the
    whole message (code puts the message there)."""
    unknown = set(fields) - set(PART_FIELDS)
    assert not unknown, f"not a PART field: {unknown}"
    return {"kind": kind, **PART_FIELDS, **fields}


def question(intent: str, **fields) -> dict:
    return part("question", intent=intent, **fields)


def understood(*parts: dict) -> dict:
    return {"parts": list(parts)}

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


def make_ctx(tmp_path, backend=None, now=NOW) -> Ctx:
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    import copy

    return Ctx(home=home, config=cfg, me=copy.deepcopy(TEST), index=Index(home, HashEmbedder()),
               backend=backend or FakeBackend([]), now=now)


def by_schema(**handlers):
    """FakeBackend reply fn that dispatches on the schema's title."""

    def reply(system, user, schema, tier):
        fn = handlers[schema["title"]]
        return fn(system, user, schema, tier) if callable(fn) else fn

    return reply

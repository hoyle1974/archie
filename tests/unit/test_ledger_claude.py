"""Review finding (Important #1): Claude sessions must count in the ledger and the
weekly journal, not just in raw `my_activity` — `ledger_answer` has its own
kind allow-list (`LISTED`) and noun table (`NOUNS`) that `claude_session` must join."""

from datetime import datetime, timezone

from archie.ask.intents.ledger import ledger_answer
from archie.ask.render import render
from archie.config import Me, load_config
from archie.ask.context import Ctx
from archie.index.db import Index
from archie.index.embed import HashEmbedder
from archie.llm.backend import FakeBackend
from archie.store.files import write_raw
from archie.store.home import init_home

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)


def _ctx(tmp_path):
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    return Ctx(home=home, config=cfg, me=Me(name="Test"), index=Index(home, HashEmbedder()),
              backend=FakeBackend([]), now=NOW)


def test_ledger_counts_and_lists_a_claude_session(tmp_path):
    ctx = _ctx(tmp_path)
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": "Claude log retention period", "project": "archie",
        "cwd": "/x", "branch": "main", "started_at": "2026-10-09T16:02:11Z",
        "ended_at": "2026-10-09T16:03:40Z", "original": "/x/s1.jsonl",
        "turns": [{"role": "user", "at": "2026-10-09T16:02:11Z", "text": "log retention question"},
                  {"role": "assistant", "at": "2026-10-09T16:03:40Z", "text": "a slim copy"}]})
    start = datetime(2026, 10, 9, tzinfo=timezone.utc)
    end = datetime(2026, 10, 10, tzinfo=timezone.utc)
    out = render(ledger_answer(ctx, start, end))
    assert "Claude session" in out.splitlines()[0]  # the top-line count
    assert "Claude sessions" in out  # the section heading
    assert "Claude log retention period" in out

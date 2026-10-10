from datetime import datetime, timezone

from archie.activity import my_activity
from archie.ask.context import Ctx
from archie.config import Me, load_config
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


def test_a_claude_session_counts_once_for_its_first_in_window_user_turn(tmp_path):
    ctx = _ctx(tmp_path)
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": "Claude log retention period", "project": "archie",
        "cwd": "/x", "branch": "main", "started_at": "2026-10-09T16:02:11Z",
        "ended_at": "2026-10-09T16:03:40Z", "original": "/x/s1.jsonl",
        "turns": [{"role": "user", "at": "2026-10-09T16:02:11Z",
                   "text": "okay, now I want to add claude logs as a source"},
                  {"role": "assistant", "at": "2026-10-09T16:03:40Z", "text": "Before going further…"},
                  {"role": "user", "at": "2026-10-09T17:00:00Z", "text": "looks good"}]})
    start, end = datetime(2026, 10, 9, tzinfo=timezone.utc), datetime(2026, 10, 10, tzinfo=timezone.utc)
    items = [i for i in my_activity(ctx, start, end) if i.kind == "claude_session"]
    assert len(items) == 1
    assert items[0].title == "Claude log retention period" and items[0].project == "archie"
    assert items[0].path == "sources/claude/archie/s1.json" and items[0].chunk == "c0-0"
    assert items[0].when == "2026-10-09T16:02:11Z"


def test_a_session_entirely_outside_the_window_is_not_an_item(tmp_path):
    ctx = _ctx(tmp_path)
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": None, "project": "archie", "cwd": "/x", "branch": "main",
        "started_at": "2026-09-01T00:00:00Z", "ended_at": "2026-09-01T00:01:00Z", "original": "/x/s1.jsonl",
        "turns": [{"role": "user", "at": "2026-09-01T00:00:00Z", "text": "old session"}]})
    start, end = datetime(2026, 10, 9, tzinfo=timezone.utc), datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert [i for i in my_activity(ctx, start, end) if i.kind == "claude_session"] == []

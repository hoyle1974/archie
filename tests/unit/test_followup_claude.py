from archie.ask.followup import show
from archie.ask.context import Ctx
from archie.config import Me, load_config
from archie.index.db import Index
from archie.index.embed import HashEmbedder
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write, write_raw
from archie.store.home import init_home
from datetime import datetime, timezone

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)


def _ctx_with_session(tmp_path, original_exists: bool):
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    ctx = Ctx(home=home, config=cfg, me=Me(name="Test"), index=Index(home, HashEmbedder()),
              backend=FakeBackend([]), now=NOW)
    original = tmp_path / "original.jsonl"
    if original_exists:
        atomic_write(original, "{}\n")
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": "Claude log retention period", "project": "archie",
        "cwd": "/x", "branch": "main", "started_at": "2026-10-09T16:02:11Z",
        "ended_at": "2026-10-09T16:03:40Z", "original": str(original),
        "turns": [{"role": "user", "at": "2026-10-09T16:02:11Z", "text": "when did we decide this?"},
                  {"role": "assistant", "at": "2026-10-09T16:03:40Z",
                   "text": "I recommend a slim copy instead of a symlink."}]})
    ctx.index.sync()
    return ctx


def _last(quote):
    return {"citations": [{"n": 1, "file": "sources/claude/archie/s1.json", "chunk": "c0-0",
                           "label": "Claude session: Claude log retention period (archie, Oct 9)",
                           "quote": quote}]}


def test_show_names_the_original_log_when_it_still_exists(tmp_path):
    ctx = _ctx_with_session(tmp_path, original_exists=True)
    out = show(ctx, _last("I recommend a slim copy instead of a symlink."), 1).plain
    assert "Full log:" in out and "original.jsonl" in out


def test_show_says_the_log_was_cleaned_up_once_it_is_gone(tmp_path):
    ctx = _ctx_with_session(tmp_path, original_exists=False)
    out = show(ctx, _last("I recommend a slim copy instead of a symlink."), 1).plain
    assert "removed by Claude Code's 30-day cleanup" in out


def test_show_on_a_non_claude_citation_is_unaffected(tmp_path):
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    ctx = Ctx(home=home, config=cfg, me=Me(name="Test"), index=Index(home, HashEmbedder()),
              backend=FakeBackend([]), now=NOW)
    atomic_write(ctx.home / "people/alex.md", "---\nname: Alex\n---\n## My notes\nPrefers snippets.\n")
    ctx.index.sync()
    last = {"citations": [{"n": 1, "file": "people/alex.md", "chunk": "c1", "label": "Alex (dossier)",
                           "quote": "Prefers snippets."}]}
    out = show(ctx, last, 1).plain
    assert "Full log" not in out and "cleanup" not in out

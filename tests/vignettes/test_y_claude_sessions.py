"""Vignette Y (docs/VIGNETTES.md): what did Claude and I decide?"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.connectors.base import SyncCtx
from archie.connectors.claude import ClaudeConnector
from archie.activity import my_activity
from archie.llm.backend import FakeBackend
from tests.support.fixtures import make_ctx, question, understood

ASSISTANT_REPLY = "Claude Code deletes its own logs after 30 days, so I recommend a slim copy instead of a symlink."


def _write_log(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _session_records():
    return [
        {"type": "user", "timestamp": "2026-10-09T16:02:11Z", "cwd": "/Users/testuser/code/archie",
         "gitBranch": "main", "message": {"role": "user", "content":
         "okay, now I want to add claude logs as a source for Archie, with sync and indexing"}},
        {"type": "assistant", "timestamp": "2026-10-09T16:03:40Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": ASSISTANT_REPLY}]}},
        {"type": "ai-title", "aiTitle": "Claude log retention period"},
    ]


def model(system, user, shape, tier):
    if shape.name == "understand":
        return understood(question("search", topic="log retention"))
    return {"summary": [{"text": "A slim copy was recommended over a symlink.",
                         "citations": [{"ref": 1, "quote": ASSISTANT_REPLY}]}],
            "sections": []}


def test_Y_ask_cites_the_claude_exchange(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb, now=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc))
    log_root = tmp_path / "claude_logs" / "archie"
    _write_log(log_root / "df9db305.jsonl", _session_records())

    sctx = SyncCtx(ctx.home, {"path": str(tmp_path / "claude_logs")}, ctx.me, ctx.now)
    asyncio.run(ClaudeConnector().sync(sctx, None))
    ctx.index.sync()

    out = render(ask(ctx, "when did we talk about log retention?"), sources=True, paths=True)
    assert "[1]" in out
    assert "sources/claude/archie/df9db305.json" in out
    assert "Claude session: Claude log retention period (archie, Oct 9)" in out


def test_Y_a_session_shows_up_in_the_days_activity(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]), now=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc))
    log_root = tmp_path / "claude_logs" / "archie"
    _write_log(log_root / "df9db305.jsonl", _session_records())
    sctx = SyncCtx(ctx.home, {"path": str(tmp_path / "claude_logs")}, ctx.me, ctx.now)
    asyncio.run(ClaudeConnector().sync(sctx, None))

    start = datetime(2026, 10, 9, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    items = [i for i in my_activity(ctx, start, end) if i.kind == "claude_session"]
    assert len(items) == 1 and items[0].title == "Claude log retention period"


def test_Y_deleting_the_original_keeps_the_copy_and_its_index_entry(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]), now=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc))
    log_root = tmp_path / "claude_logs" / "archie"
    log_path = log_root / "df9db305.jsonl"
    _write_log(log_path, _session_records())
    sctx = SyncCtx(ctx.home, {"path": str(tmp_path / "claude_logs")}, ctx.me, ctx.now)
    asyncio.run(ClaudeConnector().sync(sctx, None))
    ctx.index.sync()

    log_path.unlink()  # Claude Code's 30-day cleanup
    ctx.index.sync()  # a later sync must not drop the slim copy: nothing in sources/claude/ changed

    rel = "sources/claude/archie/df9db305.json"
    assert (ctx.home / rel).exists()
    assert ctx.index.chunk_text(rel, "c0-0")

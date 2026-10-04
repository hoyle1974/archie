from datetime import datetime, timezone

from archie.derive.cross_close import close_across_channels
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note, write_raw
from tests.support.fixtures import by_schema, make_ctx

NOW = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)


def setup(tmp_path, reply):
    calls = []

    def answer(system, user, schema, tier):
        calls.append(user)
        return reply

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(loops_cross=answer)), now=NOW)
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "open", "counterpart": "sarah_jones",
            "counterpart_name": "Sarah Jones", "summary": "Review the Redis fallback patch",
            "created_at": "2026-09-28T16:30:00+00:00", "due": None, "snoozed_until": None, "thread": "t1",
            "addressed": "to", "sources": [{"file": "sources/gmail/t1.json", "chunk": "c0", "quote": "x"}],
            "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    write_raw(ctx.home / "sources/github/acme__auth/pr-418.json", {
        "repo": "acme/auth", "number": 418, "kind": "pr", "title": "Redis fallback patch", "author": "sarahj",
        "state": "open", "body": "Adds Postgres fallback.", "created": "2026-09-28T10:00:00Z",
        "updated": "2026-09-30T18:00:00Z", "url": "u", "review_requested_me": False, "me": "ttesterson", "comments": [],
        "merged": False, "reviews": [{"author": "ttesterson", "state": "APPROVED", "body": "Looks good, ship it.",
                                      "date": "2026-09-30T18:00:00Z"}]})
    write_raw(ctx.home / "sources/github/acme__auth/commit-aaa.json", {
        "sha": "aaa", "repo": "acme/auth", "message": "Update README typo", "date": "2026-09-30T10:00:00Z",
        "author": "ttesterson", "url": "u", "files": []})
    ctx.index.sync()
    return ctx, calls


def test_strong_verified_match_closes_loop(tmp_path):
    ctx, calls = setup(tmp_path, {"done": True, "strength": "strong", "ref": 1, "quote": "Looks good, ship it."})
    close_across_channels(ctx, [])
    [lp] = load_loops(ctx.home)
    assert lp.meta["status"] == "done" and lp.meta["closed_by"]["file"] == "sources/github/acme__auth/pr-418.json"
    assert "Update README typo" not in calls[0]  # unrelated activity isn't a candidate


def test_weak_match_marks_maybe_done(tmp_path):
    ctx, _ = setup(tmp_path, {"done": True, "strength": "weak", "ref": 1, "quote": "Looks good, ship it."})
    close_across_channels(ctx, [])
    assert load_loops(ctx.home)[0].meta["status"] == "maybe_done"


def test_unverified_quote_changes_nothing_and_no_recheck_without_new_activity(tmp_path):
    ctx, calls = setup(tmp_path, {"done": True, "strength": "strong", "ref": 1, "quote": "Merged to main yesterday"})
    close_across_channels(ctx, [])
    close_across_channels(ctx, [])
    assert load_loops(ctx.home)[0].meta["status"] == "open"
    assert len(calls) == 1


def test_a_loop_whose_reply_keeps_failing_stops_costing_calls(tmp_path):
    from archie.derive.failures import MAX_TRIES

    ctx, calls = setup(tmp_path, "strength: strong")  # no `done`: unreadable
    for _ in range(MAX_TRIES + 2):
        close_across_channels(ctx, [])
    assert len(calls) == MAX_TRIES

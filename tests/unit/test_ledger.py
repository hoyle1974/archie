from datetime import datetime, timezone

from archie.ask.intents.ledger import write_week_journal
from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.llm.backend import FakeBackend
from archie.store.fence import get_fence
from archie.store.files import read_note, write_note
from tests.support.fixtures import by_schema, make_ctx, question, understood
from tests.unit.test_activity import seed

NOW = datetime(2026, 10, 2, 22, 30, tzinfo=timezone.utc)  # Fri Oct 2, 3:30 PM PDT


def test_ledger_counts_and_lists_with_citations(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("ledger", since="2026-09-28")))), now=NOW)
    seed(ctx)
    ctx.index.sync()
    out = render(ask(ctx, "what did I get done this week?"), sources=True)
    first = out.splitlines()[0]
    assert first.startswith("Sep 28 – Oct 2:")
    assert "1 commit" in first and "1 PR merged" in first and "1 review" in first and "1 issue closed" in first
    assert "Lower token TTL to 15m" in out and "[" in out
    assert "Old" not in out.split("Sources")[0]


def test_default_window_is_this_week(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("ledger")))), now=NOW)
    seed(ctx)
    ctx.index.sync()
    assert render(ask(ctx, "what did I do?")).startswith("Sep 28 – Oct 2:")


def test_long_window_groups_by_project(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("ledger", since="2026-07-01", until="2026-10-02")))), now=NOW)
    seed(ctx)
    ctx.index.sync()
    out = render(ask(ctx, "what did I accomplish this quarter?"))
    assert "acme/auth" in out


def test_weekly_journal_written_and_user_text_kept(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    seed(ctx)
    ctx.index.sync()
    path = write_week_journal(ctx)
    assert path.name == "2026-W40.md"
    note = read_note(path)
    note.body = "Proud of the TTL fix.\n\n" + note.body
    write_note(path, note)
    write_week_journal(ctx)
    again = read_note(path)
    assert "Proud of the TTL fix." in again.body and "Lower token TTL to 15m" in get_fence(again.body)


def test_long_lists_are_capped_and_commits_counted_per_repo(tmp_path):
    from archie.store.files import write_raw as wr

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("ledger", since="2026-09-28")))), now=NOW)
    for i in range(20):
        wr(ctx.home / f"sources/github/me__app/commit-{i:07d}.json", {
            "sha": f"{i:07d}", "repo": "me/app", "message": f"Change {i}", "date": f"2026-09-30T{i:02d}:00:00Z",
            "author": "ttesterson", "url": "u", "files": []})
    ctx.index.sync()
    out = render(ask(ctx, "what did I do?"))
    assert "me/app: 20 commits" in out and "…and 12 more" in out
    assert "Change 19" in out and "Change 0 " not in out

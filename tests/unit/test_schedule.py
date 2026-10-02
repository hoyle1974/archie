from datetime import datetime, timezone

from archie.briefings.schedule import tick
from archie.llm.backend import FakeBackend
from archie.store.files import read_note
from archie.tui.feed import build_feed
from tests.support.fixtures import by_schema, make_ctx
from tests.unit.test_briefings import seed, synth

MORNING = datetime(2026, 10, 1, 15, 2, tzinfo=timezone.utc)  # 8:02 AM PDT


def test_morning_tick_builds_all_of_todays_briefings_without_notifying(tmp_path):
    sent = []
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer=synth)), now=MORNING)
    seed(ctx)
    tick(ctx, notify=lambda t, m: sent.append(t))
    assert len(list((ctx.home / "briefings").rglob("*.md"))) == 2
    assert sent == []


def test_t_minus_15_notifies_once(tmp_path):
    sent = []
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer=synth)), now=MORNING)
    seed(ctx)
    tick(ctx, notify=lambda t, m: sent.append(t))
    ctx.now = datetime(2026, 10, 1, 20, 46, tzinfo=timezone.utc)
    tick(ctx, notify=lambda t, m: sent.append(t))
    tick(ctx, notify=lambda t, m: sent.append(t))
    assert sent == ["Design Review: Auth Redesign"]
    saved = [read_note(p).meta for p in (ctx.home / "briefings").rglob("*.md")]
    assert any(m["notified"] for m in saved)


def test_feed_shows_next_briefing_and_top_loops(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer=synth)), now=MORNING)
    seed(ctx)
    tick(ctx, notify=lambda t, m: None)
    feed = build_feed(ctx)
    assert feed.startswith("Next: 2:00 PM · Design Review: Auth Redesign")
    assert "Review Alex's Redis fallback logic" in feed


def test_feed_without_meetings(tmp_path):
    ctx = make_ctx(tmp_path, now=MORNING)
    assert "No more meetings today" in build_feed(ctx)


def test_friday_afternoon_tick_writes_weekly_journal(tmp_path):
    ctx = make_ctx(tmp_path, now=datetime(2026, 10, 2, 22, 30, tzinfo=timezone.utc))  # Fri 3:30 PM PDT
    tick(ctx, notify=lambda t, m: None)
    assert (ctx.home / "journal/weekly/2026-W40.md").exists()


def test_thursday_tick_writes_no_journal(tmp_path):
    ctx = make_ctx(tmp_path, now=datetime(2026, 10, 1, 22, 30, tzinfo=timezone.utc))
    tick(ctx, notify=lambda t, m: None)
    assert not (ctx.home / "journal/weekly").exists() or not list((ctx.home / "journal/weekly").iterdir())

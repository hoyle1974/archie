from datetime import datetime, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import load_loops
from archie.derive.meetings import load_meetings
from archie.llm.backend import FakeBackend
from archie.store.fence import get_fence
from archie.store.files import read_note
from tests.support.fixtures import by_schema, make_ctx
from tests.unit.test_briefings import seed

AFTER = datetime(2026, 10, 1, 21, 50, tzinfo=timezone.utc)  # 2:50 PM PDT, review just ended
NOTES = "Redis approved. Alex to add circuit breaker. I need to update the runbook by next Wed."


def route(meeting):
    return {"intent": "notes", "params": {"people": [], "since": None, "until": None, "topic": None,
                                          "meeting": meeting, "text": NOTES}}


ACTIONS = {"items": [
    {"owner": "me", "text": "Update the runbook", "due": "2099-01-01",  # ignored: code reads "next Wed"
     "quote": "I need to update the runbook by next Wed"},
    {"owner": "Alex", "text": "Add circuit breaker", "due": None, "quote": "Alex to add circuit breaker"},
    {"owner": "Priya", "text": "Ship it", "due": None, "quote": "Priya ships it tomorrow"}]}


def test_notes_are_saved_verbatim_and_action_items_become_loops(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("design review"), notes_actions=ACTIONS)), now=AFTER)
    seed(ctx)
    out = render(ask(ctx, f"notes from the design review: {NOTES}"))
    m = next(x for x in load_meetings(ctx.home) if x.meta["title"].startswith("Design Review"))
    body = read_note(ctx.home / m.rel_path).body
    assert NOTES in body.split("<!-- archie:auto -->")[0]
    assert "Update the runbook" in get_fence(body)
    loops = {lp.meta["summary"]: lp.meta for lp in load_loops(ctx.home)}
    assert loops["Update the runbook"]["kind"] == "i_promised" and loops["Update the runbook"]["due"] == "2026-10-07"
    assert loops["Add circuit breaker"]["kind"] == "waiting_on"
    assert loops["Add circuit breaker"]["counterpart"] == "alex_rivera"
    assert "Ship it" not in loops  # fabricated quote dropped
    assert "Design Review" in out and "2 action items" in out


def test_defaults_to_meeting_that_just_ended(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route(None), notes_actions={"items": []})), now=AFTER)
    seed(ctx)
    out = render(ask(ctx, f"my notes: {NOTES}"))
    assert "Design Review" in out


def test_notes_with_no_meeting_become_standalone(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("hallway chat"), notes_actions={"items": []})),
                   now=AFTER)
    out = render(ask(ctx, "notes from hallway chat: Redis approved."))
    assert "Saved" in out
    assert any("hallway" in p.name for p in (ctx.home / "meetings").rglob("*.md"))

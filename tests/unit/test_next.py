from datetime import datetime, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import Loop, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import by_schema, make_ctx, question, understood
from tests.unit.test_briefings import seed

AT = datetime(2026, 10, 1, 20, 10, tzinfo=timezone.utc)  # 1:10 PM PDT, review at 2:00
ROUTE = understood(question("next"))


def add_loop(ctx, i, kind, who, cid, summary, created, due=None):
    meta = {"loop_id": f"l{i}", "kind": kind, "status": "open", "counterpart": cid, "counterpart_name": who,
            "summary": summary, "created_at": created, "due": due, "snoozed_until": None, "thread": "t",
            "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop(f"l{i}", f"loops/2026/l{i}.md", Note(meta=meta, body="")))


def test_next_uses_free_time_and_ranked_loops_without_llm(tmp_path):
    fb = FakeBackend(by_schema(understand=ROUTE))
    ctx = make_ctx(tmp_path, fb, now=AT)
    seed(ctx)  # includes "Review Alex's Redis fallback logic", due today, Alex is in the 2pm
    add_loop(ctx, 2, "i_promised", "Ken Ito", "ken_ito", "Send Ken the Q4 numbers", "2026-09-26T17:00:00+00:00")
    add_loop(ctx, 3, "waiting_on", "Priya Sharma", "priya_sharma", "SSO launch date", "2026-09-25T17:00:00+00:00")
    out = render(ask(ctx, "what should I work on next?"))
    first = out.splitlines()[0]
    assert first.startswith("You have 50 minutes before Design Review: Auth Redesign (2:00 PM).")
    assert "Review Alex's Redis fallback logic" in first
    assert out.index("Review Alex's") < out.index("Send Ken")
    assert "you're meeting them soon" in out
    assert "Nudge" in out and "SSO launch date" in out
    assert fb.calls == []  # quick-routed, and ranking is code


def test_clear_calendar_and_nothing_open(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE)), now=AT)
    out = render(ask(ctx, "what next?"))
    assert "calendar is clear" in out and "nothing open" in out.lower()

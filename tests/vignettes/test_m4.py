"""M4 vignettes (docs/VIGNETTES.md): A (all-hands), G, I, K."""

from datetime import datetime, timezone

from archie.briefings.schedule import tick
from archie.store.fence import get_fence
from archie.store.files import read_note
from tests.vignettes.week import Week


def test_I_back_from_time_off(tmp_path):
    w = Week(tmp_path, now=datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc), work=True)
    out = w.ask("what happened while I was out since Sep 28?")
    assert "Opened while you were out" in out
    assert "Can you review my fallback logic by today" in out  # a loop opened in the window
    seen = w.llm.saw("answer")
    assert "auth migration is paused" in seen and "Ten things you missed" not in seen  # no newsletters


def test_G_project_handover(tmp_path):
    w = Week(tmp_path, work=True)
    out = w.ask("write a handover for the redis migration")
    seen = w.llm.saw("answer")
    assert "Redis fallback patch" in seen and "Fix redis connection pool drop" in seen
    assert "Alex Rivera" in out  # people involved, code-computed
    saved = list((w.ctx.home / "projects").glob("*handover*.md"))
    assert saved and "Alex Rivera" in saved[0].read_text()


def test_K_weekly_brag_doc(tmp_path):
    w = Week(tmp_path, now=datetime(2026, 10, 2, 22, 30, tzinfo=timezone.utc), work=True)  # Fri 3:30 PM
    tick(w.ctx, notify=lambda t, m: None)
    note = read_note(w.ctx.home / "journal/weekly/2026-W40.md")
    assert "Lower token TTL to 15m" in get_fence(note.body)
    assert "Approved PR #418 Redis fallback patch" in get_fence(note.body)


def test_A_all_hands_keeps_to_company_level(tmp_path):
    w = Week(tmp_path, work=True)
    from archie.connectors.calendar import normalize_event
    from archie.derive.meetings import derive_meetings
    from archie.store.files import write_raw
    from tests.support.fake_google import cal_event
    from tests.vignettes.week import ME

    crowd = [(ME, "Test")] + [(f"p{i}@acme.example", f"Person {i}") for i in range(30)]
    ev = cal_event("ah", "Q4 All-Hands", "2026-10-01T22:00:00Z", "2026-10-01T23:00:00Z", attendees=crowd)
    p = w.ctx.home / "sources/calendar/ah.json"
    write_raw(p, normalize_event(ev, w.ctx.me))
    derive_meetings(w.ctx, [p])
    w.ctx.index.sync()
    w.ctx.now = datetime(2026, 10, 1, 21, 50, tzinfo=timezone.utc)
    out = w.ask("prep me for the all-hands")
    assert out.splitlines()[0] == "3:00 PM · Q4 All-Hands · 60 min"
    assert "31 people invited." in out and "Person 3" not in out

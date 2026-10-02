from datetime import datetime, timezone

from archie.briefings.classify import classify
from archie.connectors.calendar import normalize_event
from archie.derive.meetings import derive_meetings, find_meeting, load_meetings
from archie.store.files import read_note, write_note, write_raw
from tests.support.fake_google import cal_event
from tests.support.fixtures import TEST, make_ctx

NOW = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)


def put(ctx, ev):
    path = ctx.home / f"sources/calendar/{ev['id']}.json"
    write_raw(path, normalize_event(ev, TEST))
    return path


def one_on_one(eid="ev_20261007", start="2026-10-07T21:00:00Z"):
    return cal_event(eid, "Alex / Test", start, start.replace("21:00", "21:30"),
                     attendees=[("test@acme.example", "Test"), ("alex@acme.example", "Alex Rivera")], recurring="ev")


def test_meeting_note_created_with_type_and_attendees(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    derive_meetings(ctx, [put(ctx, one_on_one())])
    [m] = load_meetings(ctx.home)
    assert m.meta["type"] == "one_on_one"
    assert m.meta["attendees"] == ["alex_rivera"]
    assert m.meta["series_id"] == "ev"
    assert m.rel_path.startswith("meetings/2026/2026-10-07-alex-test")
    assert (ctx.home / "people/alex_rivera.md").exists()


def test_future_meeting_does_not_move_last_interaction_forward(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    derive_meetings(ctx, [put(ctx, one_on_one())])
    meta = read_note(ctx.home / "people/alex_rivera.md").meta
    assert meta["last_interaction"] is None  # an invite isn't an interaction
    assert meta["first_seen"] == NOW.isoformat()
    assert meta["status"] == "stub"


def test_solo_events_are_personal_events_without_briefings(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    focus = cal_event("f1", "Focus time", "2026-10-02T16:00:00Z", "2026-10-02T18:00:00Z",
                      attendees=[("test@acme.example", "Test")])
    test = cal_event("t1", "Test", "2026-10-02T18:30:00Z", "2026-10-02T19:00:00Z")
    derive_meetings(ctx, [put(ctx, focus), put(ctx, test)])
    ms = load_meetings(ctx.home)
    assert sorted(m.meta["title"] for m in ms) == ["Focus time", "Test"]
    assert all(m.meta["type"] == "event" and m.meta["attendees"] == [] for m in ms)


def test_all_day_events_are_skipped(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    ev = cal_event("ad", "Pizza Day", "2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z")
    ev["start"], ev["end"] = {"date": "2026-10-21"}, {"date": "2026-10-22"}
    derive_meetings(ctx, [put(ctx, ev)])
    assert load_meetings(ctx.home) == []


def test_rederive_updates_same_file_and_keeps_user_notes(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    derive_meetings(ctx, [put(ctx, one_on_one())])
    [m] = load_meetings(ctx.home)
    path = ctx.home / m.rel_path
    note = read_note(path)
    note.body = note.body.replace("## My notes\n", "## My notes\nTalked about Redis.\n")
    write_note(path, note)
    ev = one_on_one()
    ev["summary"] = "Alex / Test (moved)"
    derive_meetings(ctx, [put(ctx, ev)])
    [again] = load_meetings(ctx.home)
    assert again.rel_path == m.rel_path
    assert again.meta["title"] == "Alex / Test (moved)"
    assert "Talked about Redis." in read_note(path).body


def test_cancelled_event_marks_meeting_cancelled(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    derive_meetings(ctx, [put(ctx, one_on_one())])
    from archie.store.files import tombstone

    p = ctx.home / "sources/calendar/ev_20261007.json"
    tombstone(p, NOW.isoformat())
    derive_meetings(ctx, [p])
    assert load_meetings(ctx.home)[0].meta["status"] == "cancelled"


def test_find_meeting_by_event_id(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    derive_meetings(ctx, [put(ctx, one_on_one())])
    assert find_meeting(ctx.home, "ev_20261007").meta["title"] == "Alex / Test"


def ev(title, n_others, recurring=None):
    return {"title": title, "series_id": recurring,
            "attendees": [{"email": "test@acme.example", "self": True}] +
                         [{"email": f"p{i}@x.example", "self": False} for i in range(n_others)]}


def test_classify_rules_in_order(tmp_path):
    cfg = {"briefings": {"all_hands_min_attendees": 25}}
    assert classify(ev("Alex / Test", 1, "s1"), cfg, {}) == "one_on_one"
    assert classify(ev("Coffee chat", 1), cfg, {}) == "standard"
    assert classify(ev("Daily Standup", 6, "s2"), cfg, {}) == "standup"
    assert classify(ev("Q4 Town Hall", 3), cfg, {}) == "all_hands"
    assert classify(ev("Big sync", 40), cfg, {}) == "all_hands"
    assert classify(ev("Design Review", 3), cfg, {}) == "standard"
    assert classify(ev("Alex / Test", 1, "s1"), cfg, {"series": {"s1": "standard"}}) == "standard"
    assert classify(ev("Weekly thing", 5), cfg, {"titles": {"Weekly thing": "standup"}}) == "standup"


def test_declined_meetings_get_no_briefing(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    ev = one_on_one()
    ev["attendees"][0]["responseStatus"] = "declined"
    derive_meetings(ctx, [put(ctx, ev)])
    [m] = load_meetings(ctx.home)
    assert m.meta["status"] == "declined"
    from archie.briefings.build import upcoming
    assert upcoming(ctx, hours=24 * 30) == []


def test_user_edited_type_wins_over_reclassification(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    derive_meetings(ctx, [put(ctx, one_on_one())])
    [m] = load_meetings(ctx.home)
    note = read_note(ctx.home / m.rel_path)
    note.meta["type"] = "standard"  # the user edits the file directly
    write_note(ctx.home / m.rel_path, note)
    ev = one_on_one()
    ev["summary"] = "Alex / Test (renamed)"
    derive_meetings(ctx, [put(ctx, ev)])
    again = load_meetings(ctx.home)[0]
    assert again.meta["type"] == "standard" and again.meta["title"] == "Alex / Test (renamed)"

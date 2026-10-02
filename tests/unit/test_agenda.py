from datetime import datetime, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.connectors.calendar import normalize_event
from archie.derive.meetings import derive_meetings
from archie.llm.backend import FakeBackend
from archie.store.files import write_raw
from tests.support.fake_google import cal_event
from tests.support.fixtures import TEST, by_schema, make_ctx

NOW = datetime(2026, 10, 2, 18, 30, tzinfo=timezone.utc)  # Fri Oct 2, 11:30 AM PDT


def put(ctx, ev, calendar="primary"):
    data = normalize_event(ev, TEST)
    data["calendar"] = calendar
    write_raw(ctx.home / f"sources/calendar/{ev['id']}.json", data)
    return ctx.home / f"sources/calendar/{ev['id']}.json"


def seed(ctx):
    paths = [
        put(ctx, cal_event("a", "Train of lights tickets", "2026-10-03T17:00:00Z", "2026-10-03T17:30:00Z"),
            "Strohm's Calendar"),
        put(ctx, cal_event("b", "Goodspouse - greenhouse cake pick up", "2026-10-03T17:30:00Z", "2026-10-03T18:00:00Z"),
            "Strohm's Calendar"),
        put(ctx, cal_event("c", "Design Review", "2026-10-05T21:00:00Z", "2026-10-05T21:45:00Z",
                           attendees=[("test@acme.example", "Test"), ("alex@acme.example", "Alex Rivera")])),
    ]
    allday = cal_event("d", "No Childone School", "2026-10-03T00:00:00Z", "2026-10-04T00:00:00Z")
    allday["start"], allday["end"] = {"date": "2026-10-03"}, {"date": "2026-10-04"}
    paths.append(put(ctx, allday, "Strohm's Calendar"))
    declined = cal_event("e", "Optional sync", "2026-10-03T19:00:00Z", "2026-10-03T19:30:00Z",
                         attendees=[("test@acme.example", "Test"), ("x@acme.example", "X")])
    declined["attendees"][0]["responseStatus"] = "declined"
    paths.append(put(ctx, declined))
    derive_meetings(ctx, paths)


def test_tomorrow_lists_all_day_then_timed_without_a_model_call(tmp_path):
    fb = FakeBackend([])
    ctx = make_ctx(tmp_path, fb, now=NOW)
    seed(ctx)
    out = render(ask(ctx, "What do I have planned for tomorrow?"))
    lines = out.splitlines()
    assert lines[0] == "Saturday, Oct 3"
    assert lines[1] == "  All day  No Childone School"
    assert lines[2] == "  10:00 AM  Train of lights tickets"
    assert lines[3] == "  10:30 AM  Goodspouse - greenhouse cake pick up"
    assert "Optional sync" not in out  # declined
    assert fb.calls == []


def test_routed_window_and_meeting_attendees(tmp_path):
    route = {"intent": "agenda", "params": {"people": [], "since": "2026-10-03", "until": "2026-10-05",
                                            "topic": None, "meeting": None, "text": None}}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route)), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "what's my weekend and monday look like"))
    assert "Monday, Oct 5" in out and "2:00 PM  Design Review · with Alex Rivera" in out
    assert "Sunday, Oct 4\n  Nothing on your calendar." in out


def test_brief_does_not_prep_personal_events(tmp_path):
    from archie.briefings.build import pick_meeting

    ctx = make_ctx(tmp_path, now=NOW)
    seed(ctx)
    assert pick_meeting(ctx, None) is None  # tomorrow's personal events are not prep candidates
    from archie.ask.intents.brief import brief_intent

    assert "no upcoming meetings" in render(brief_intent(ctx, "prep me", {"meeting": None})).lower()

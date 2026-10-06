import asyncio
from datetime import datetime, timezone

from archie.connectors.base import SyncCtx
from archie.connectors.calendar import CalendarConnector
from archie.index.chunk import chunk_file
from archie.store.files import read_raw
from archie.store.home import init_home
from tests.support.fake_google import FakeCalendar, cal_event
from tests.support.fixtures import TEST

NOW = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)
REVIEW = cal_event("ev1", "Design Review: Auth Redesign", "2026-10-01T21:00:00Z", "2026-10-01T21:45:00Z",
                   attendees=[("test@acme.example", "Test"), ("alex@acme.example", "Alex Rivera"),
                              ("priya@acme.example", "Priya Sharma")],
                   description="<p>Agenda: Redis cluster</p>",
                   attachments=[{"fileId": "doc1", "title": "Auth_Migration_Draft", "fileUrl": "https://docs/x",
                                 "mimeType": "application/vnd.google-apps.document"}])


def sync(fake, cursor=None, tmp_path=None):
    home = init_home(tmp_path / "h")
    res = asyncio.run(CalendarConnector(service_factory=lambda: fake).sync(SyncCtx(home, {}, TEST, NOW, 14), cursor))
    return home, res


def test_first_sync_uses_backfill_window_and_saves_token(tmp_path):
    fake = FakeCalendar([REVIEW])
    home, res = sync(fake, tmp_path=tmp_path)
    assert fake.requests[0]["timeMin"].startswith("2026-09-17")
    assert fake.requests[0]["singleEvents"] is True
    assert res.cursor == {"calendars": {"primary": "tok1"}, "utc": True, "window_end": "2026-11-30T16:00:00+00:00"}
    data = read_raw(home / "sources/calendar/ev1.json")
    assert data["title"] == "Design Review: Auth Redesign"
    assert data["start"] == "2026-10-01T21:00:00+00:00"
    assert [a["email"] for a in data["attendees"]] == ["test@acme.example", "alex@acme.example", "priya@acme.example"]
    assert data["attendees"][0]["self"] is True
    assert data["attachments"][0]["file_id"] == "doc1"


def test_incremental_uses_sync_token(tmp_path):
    fake = FakeCalendar([REVIEW], sync_token="tok2")
    home, res = sync(fake, cursor={"sync_token": "tok1"}, tmp_path=tmp_path)
    assert fake.requests[0]["syncToken"] == "tok1" and "timeMin" not in fake.requests[0]
    assert res.cursor == {"calendars": {"primary": "tok2"}, "utc": True, "window_end": "2026-11-30T16:00:00+00:00"}


def test_expired_token_does_full_resync(tmp_path):
    fake = FakeCalendar([REVIEW])
    fake.token_expired = True
    home, res = sync(fake, cursor={"sync_token": "old"}, tmp_path=tmp_path)
    assert "timeMin" in fake.requests[-1]
    assert res.written


def test_cancelled_event_becomes_tombstone(tmp_path):
    fake = FakeCalendar([REVIEW])
    home, _ = sync(fake, tmp_path=tmp_path)
    fake.events_data = [{"id": "ev1", "status": "cancelled"}]
    asyncio.run(CalendarConnector(service_factory=lambda: fake).sync(SyncCtx(home, {}, TEST, NOW, 14), {"sync_token": "t"}))
    data = read_raw(home / "sources/calendar/ev1.json")
    assert data["deleted"] is True and data["title"] == "Design Review: Auth Redesign"


def test_event_chunk_is_readable_with_people(tmp_path):
    home, _ = sync(FakeCalendar([REVIEW]), tmp_path=tmp_path)
    [c] = chunk_file("sources/calendar/ev1.json", (home / "sources/calendar/ev1.json").read_text())
    assert "Alex Rivera" in c.text and "Agenda: Redis cluster" in c.text and "<p>" not in c.text
    assert c.label.startswith("Event: Design Review: Auth Redesign (")
    assert "alex@acme.example" in c.people and c.ts == "2026-10-01T21:00:00+00:00"


def test_all_calendars_i_own_or_edit_are_synced_but_not_subscriptions(tmp_path):
    family = cal_event("fam1", "Test - this is to test my system", "2026-10-02T18:30:00Z", "2026-10-02T19:00:00Z")
    hol = cal_event("hol1", "Columbus Day", "2026-10-12T00:00:00Z", "2026-10-12T01:00:00Z")
    fake = FakeCalendar([REVIEW], others={"fam@group.example": ("Strohm's Calendar", "owner", [family]),
                                           "holidays@group.example": ("Holidays", "reader", [hol])})
    home, res = sync(fake, tmp_path=tmp_path)
    names = sorted(p.name for p in res.written)
    assert "ev1.json" in names and any(n.endswith("_fam1.json") for n in names)
    assert not any("hol1" in n for n in names)
    fam = read_raw(next(p for p in res.written if p.name.endswith("_fam1.json")))
    assert fam["calendar"] == "Strohm's Calendar" and fam["title"].startswith("Test")
    assert res.cursor["calendars"]["fam@group.example"] == "fam@group.example-tok"


def test_old_single_token_cursor_still_works(tmp_path):
    fake = FakeCalendar([REVIEW], sync_token="tok2")
    home, res = sync(fake, cursor={"sync_token": "tok1"}, tmp_path=tmp_path)
    assert fake.requests[0]["syncToken"] == "tok1"


def test_times_are_stored_in_utc_and_old_local_offsets_are_rewritten_once(tmp_path):
    from archie.connectors.calendar import normalize_event
    from archie.store.files import write_raw

    local = cal_event("ev9", "Cake pickup", "2026-10-03T10:30:00-07:00", "2026-10-03T11:00:00-07:00")
    data = normalize_event(local, TEST)
    assert (data["start"], data["end"]) == ("2026-10-03T17:30:00+00:00", "2026-10-03T18:00:00+00:00")

    home = init_home(tmp_path / "h")
    old = {**data, "id": "old", "start": "2026-10-02T16:00:00-07:00", "end": "2026-10-02T16:30:00-07:00"}
    write_raw(home / "sources/calendar/old.json", old)
    fake = FakeCalendar([])
    res = asyncio.run(CalendarConnector(service_factory=lambda: fake).sync(SyncCtx(home, {}, TEST, NOW, 14), None))
    assert read_raw(home / "sources/calendar/old.json")["start"] == "2026-10-02T23:00:00+00:00"
    assert home / "sources/calendar/old.json" in res.written  # so meetings and the index pick it up
    again = asyncio.run(CalendarConnector(service_factory=lambda: fake).sync(SyncCtx(home, {}, TEST, NOW, 14),
                                                                             res.cursor))
    assert again.written == []  # done once


def _weekly(start, weeks):
    from datetime import timedelta

    out = []
    for i in range(weeks):
        s = start + timedelta(weeks=i)
        e = s + timedelta(hours=1)
        out.append(cal_event(f"swim_{s:%Y%m%dT%H%M%SZ}", "Swimming", s.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             e.strftime("%Y-%m-%dT%H:%M:%SZ"), recurring="swim"))
    return out


def test_an_edited_series_keeps_only_copies_inside_the_lookahead(tmp_path):
    fake = FakeCalendar(_weekly(NOW, 52 * 3), sync_token="tok2")  # Google sends every copy of an edited series
    edge = datetime(2026, 11, 30, 16, 0, tzinfo=timezone.utc).isoformat()  # NOW + 60 days: no roll needed
    home, res = sync(fake, cursor={"calendars": {"primary": "tok1"}, "utc": True, "window_end": edge},
                     tmp_path=tmp_path)
    kept = sorted(p.name for p in (home / "sources/calendar").glob("swim_*.json"))
    assert len(kept) == 9  # 60 days of weekly copies, not three years
    assert kept[-1] == "swim_20261126T160000Z.json"


def test_the_window_rolls_forward_to_fetch_copies_that_never_changed(tmp_path):
    from datetime import timedelta

    fake = FakeCalendar([], sync_token="tok2", full=_weekly(NOW, 20))  # nothing changed since the last sync
    home = init_home(tmp_path / "h")
    later = NOW + timedelta(days=21)
    edge = NOW + timedelta(days=60)
    cursor = {"calendars": {"primary": "tok1"}, "utc": True, "window_end": edge.isoformat()}
    res = asyncio.run(CalendarConnector(service_factory=lambda: fake).sync(SyncCtx(home, {}, TEST, later, 14), cursor))
    windowed = [r for r in fake.requests if "timeMin" in r]
    assert [r["timeMin"] for r in windowed] == [edge.isoformat()]
    assert res.cursor["window_end"] == (later + timedelta(days=60)).isoformat()
    got = sorted(p.name for p in (home / "sources/calendar").glob("swim_*.json"))
    assert got == ["swim_20261203T160000Z.json", "swim_20261210T160000Z.json", "swim_20261217T160000Z.json"]


def test_copies_already_stored_past_the_window_are_removed(tmp_path):
    from archie.store.files import write_raw

    home = init_home(tmp_path / "h")
    far = home / "sources/calendar/swim_20400102T173000Z.json"
    far.parent.mkdir(parents=True, exist_ok=True)
    write_raw(far, {"id": "swim_20400102T173000Z", "start": "2040-01-02T17:30:00+00:00",
                    "end": "2040-01-02T18:30:00+00:00", "title": "Swimming"})
    allday = home / "sources/calendar/school_off.json"  # all-day events store a bare date
    write_raw(allday, {"id": "school_off", "start": "2026-10-03", "end": "2026-10-04", "all_day": True})
    far_day = home / "sources/calendar/far_off.json"
    write_raw(far_day, {"id": "far_off", "start": "2030-10-03", "end": "2030-10-04", "all_day": True})
    fake = FakeCalendar([], sync_token="tok2")
    res = asyncio.run(CalendarConnector(service_factory=lambda: fake).sync(
        SyncCtx(home, {}, TEST, NOW, 14), {"calendars": {"primary": "tok1"}, "utc": True}))
    assert not far.exists() and far in res.deleted
    assert allday.exists() and not far_day.exists()

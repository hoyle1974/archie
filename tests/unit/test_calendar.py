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
    assert res.cursor == {"sync_token": "tok1"}
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
    assert res.cursor == {"sync_token": "tok2"}


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

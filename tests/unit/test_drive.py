import asyncio
from datetime import datetime, timezone

from archie.connectors.base import SyncCtx
from archie.connectors.calendar import normalize_event
from archie.connectors.drive import DriveConnector
from archie.index.chunk import chunk_file
from archie.store.files import read_raw, write_raw
from archie.store.home import init_home
from tests.support.fake_google import FakeDrive, cal_event, drive_file
from tests.support.fixtures import TEST

NOW = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)
MINE = drive_file("d1", "Auth notes", "2026-09-30T10:00:00Z")
THEIRS = drive_file("d2", "Auth_Migration_Draft", "2026-10-01T15:30:00Z", owner="alex@acme.example",
                    modifier="alex@acme.example")
RANDOM = drive_file("d3", "Party planning", "2026-09-29T10:00:00Z", owner="x@y.example", modifier="x@y.example")
TEXTS = {"d1": "# Auth notes\nRedis cluster plan.", "d2": "Moving session tokens to Redis.", "d3": "Cake."}


def run(fake, cursor=None, home=None, tmp_path=None):
    home = home or init_home(tmp_path / "h")
    res = asyncio.run(DriveConnector(service_factory=lambda: fake).sync(SyncCtx(home, {}, TEST, NOW, 14), cursor))
    return home, res


def test_first_sync_takes_my_docs_and_meeting_attachments_only(tmp_path):
    home = init_home(tmp_path / "h")
    ev = cal_event("ev1", "Design Review", "2026-10-01T21:00:00Z", "2026-10-01T21:45:00Z",
                   attachments=[{"fileId": "d2", "title": "Auth_Migration_Draft", "fileUrl": "u", "mimeType": "x"}])
    write_raw(home / "sources/calendar/ev1.json", normalize_event(ev, TEST))
    fake = FakeDrive([MINE, THEIRS, RANDOM], TEXTS)
    home, res = run(fake, home=home)
    assert sorted(p.name for p in res.written) == ["d1.json", "d2.json"]
    assert res.cursor == {"page_token": "100"}
    d2 = read_raw(home / "sources/drive/d2.json")
    assert d2["title"] == "Auth_Migration_Draft" and d2["text"] == "Moving session tokens to Redis."
    assert d2["modified_by"] == "alex@acme.example" and d2["attached_to_meeting"] is True


def test_incremental_uses_changes_feed(tmp_path):
    fake = FakeDrive([MINE, THEIRS, RANDOM], TEXTS)
    fake.changes_list = [{"fileId": "d1", "removed": False, "file": MINE}, {"fileId": "d3", "removed": False, "file": RANDOM}]
    home, res = run(fake, cursor={"page_token": "100"}, tmp_path=tmp_path)
    assert [p.name for p in res.written] == ["d1.json"]
    assert res.cursor == {"page_token": "101"}


def test_trashed_or_removed_file_is_tombstoned(tmp_path):
    fake = FakeDrive([MINE], TEXTS)
    home, _ = run(fake, tmp_path=tmp_path)
    fake.changes_list = [{"fileId": "d1", "removed": True}]
    home, res = run(fake, cursor={"page_token": "100"}, home=home)
    assert read_raw(home / "sources/drive/d1.json")["deleted"] is True


def test_doc_chunks_are_labeled(tmp_path):
    home, _ = run(FakeDrive([MINE], TEXTS), tmp_path=tmp_path)
    [c] = chunk_file("sources/drive/d1.json", (home / "sources/drive/d1.json").read_text())
    assert c.label.startswith("Doc: Auth notes (edited ") and "Redis cluster plan." in c.text
    assert "test@acme.example" in c.people


def test_incremental_fetches_newly_attached_docs(tmp_path):
    home = init_home(tmp_path / "h")
    fake = FakeDrive([MINE, THEIRS], TEXTS)
    ev = cal_event("ev1", "Design Review", "2026-10-01T21:00:00Z", "2026-10-01T21:45:00Z",
                   attachments=[{"fileId": "d2", "title": "Auth_Migration_Draft", "fileUrl": "u", "mimeType": "x"}])
    write_raw(home / "sources/calendar/ev1.json", normalize_event(ev, TEST))
    home, res = run(fake, cursor={"page_token": "100"}, home=home)
    assert [p.name for p in res.written] == ["d2.json"]

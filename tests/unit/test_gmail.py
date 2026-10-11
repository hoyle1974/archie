import asyncio
from datetime import datetime, timezone

from archie.connectors.base import SyncCtx
from archie.connectors.gmail import GmailConnector
from archie.index.chunk import chunk_file
from archie.store.files import read_raw
from archie.store.home import init_home
from tests.support.fake_google import FakeGmail, gmail_message
from tests.support.fixtures import TEST

NOW = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)

ASK = gmail_message("m1", "t1", "Sarah Jones <sarah.j@acme.example>", "Test Testerson <test@acme.example>",
                    "Redis fallback", "Hi Test,\nCan you review the Redis fallback patch before Friday?\n\nThanks,\nSarah\n-- \nSarah Jones | Staff Eng",
                    datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc))
REPLY = gmail_message("m2", "t1", "Test Testerson <test@acme.example>", "sarah.j@acme.example", "Re: Redis fallback",
                      "Yes, will do today.\n\nOn Wed, Oct 1, 2026 at 9:30 AM Sarah Jones wrote:\n> Hi Test,\n> Can you review",
                      datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc), labels=("SENT",))


def sync(fake, cursor=None, tmp_path=None):
    home = init_home(tmp_path / "h")
    conn = GmailConnector(service_factory=lambda: fake)
    sctx = SyncCtx(home, {}, TEST, NOW, 14)
    return home, asyncio.run(conn.sync(sctx, cursor))


def test_first_sync_backfills_14_days_and_writes_threads(tmp_path):
    fake = FakeGmail({"t1": [ASK, REPLY]})
    home, res = sync(fake, tmp_path=tmp_path)
    assert f"after:{int(datetime(2026, 9, 17, 16, tzinfo=timezone.utc).timestamp())}" in fake.queries[0]
    assert res.cursor == {"last_sync": NOW.isoformat()}
    data = read_raw(home / "sources/gmail/t1.json")
    assert [m["from_email"] for m in data["messages"]] == ["sarah.j@acme.example", "test@acme.example"]
    assert data["messages"][0]["date"] == "2026-10-01T09:30:00+00:00"
    assert "review the Redis fallback patch" in data["messages"][0]["body"]
    assert data["messages"][1]["from_me"] is True


def test_later_syncs_ask_only_for_mail_since_the_last_sync_with_an_hour_of_overlap(tmp_path):
    late = gmail_message("m9", "t2", "Sarah Jones <sarah.j@acme.example>", "test@acme.example", "Later", "hi",
                         datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc))
    fake = FakeGmail({"t1": [ASK], "t2": [late]})
    home, res = sync(fake, cursor={"last_sync": "2026-10-01T15:45:00+00:00"}, tmp_path=tmp_path)
    assert f"after:{int(datetime(2026, 10, 1, 14, 45, tzinfo=timezone.utc).timestamp())}" in fake.queries[0]
    assert fake.fetched == ["t2"] and [p.name for p in res.written] == ["t2.json"]
    assert res.cursor == {"last_sync": NOW.isoformat()}


def test_a_thread_already_mirrored_in_full_is_not_fetched_again(tmp_path):
    fake = FakeGmail({"t1": [ASK, REPLY]})
    sync(fake, tmp_path=tmp_path)
    fake.fetched.clear()
    fake.thread_data["t1"].append(gmail_message("m3", "t1", "Sarah Jones <sarah.j@acme.example>", "test@acme.example",
                                                "Re: Redis fallback", "Thanks!", datetime(2026, 10, 1, 11, tzinfo=timezone.utc)))
    fake.thread_data["t3"] = [gmail_message("m4", "t3", "a@b.example", "test@acme.example", "x", "y",
                                            datetime(2026, 10, 1, 12, tzinfo=timezone.utc))]
    _, res = sync(fake, cursor={"last_sync": "2026-09-30T00:00:00+00:00"}, tmp_path=tmp_path)
    assert sorted(fake.fetched) == ["t1", "t3"]  # t1 has a new message; nothing unchanged is refetched
    sync(fake, cursor={"last_sync": "2026-09-30T00:00:00+00:00"}, tmp_path=tmp_path)
    assert sorted(fake.fetched) == ["t1", "t3"]


def test_an_old_history_cursor_is_read_as_a_date(tmp_path):
    fake = FakeGmail({"t1": [ASK]})
    _, res = sync(fake, cursor={"history_id": "1", "last_sync": "2026-09-30T00:00:00+00:00"}, tmp_path=tmp_path)
    assert [p.name for p in res.written] == ["t1.json"] and "after:" in fake.queries[-1]


def test_rate_limit_waits_and_progress_are_said_out_loud(tmp_path):
    from archie.connectors import google_retry

    heard = []
    fake = FakeGmail({f"t{i}": [gmail_message(f"m{i}", f"t{i}", "a@b.example", "test@acme.example", "s", "b",
                                              datetime(2026, 10, 1, 9, tzinfo=timezone.utc))] for i in range(120)})
    fake.rate_limited = 1
    google_retry.SLEEP = lambda s: None
    try:
        home = init_home(tmp_path / "h")
        sctx = SyncCtx(home, {}, TEST, NOW, 14, say=heard.append)
        asyncio.run(GmailConnector(service_factory=lambda: fake).sync(sctx, None))
    finally:
        google_retry.SLEEP = __import__("time").sleep
    assert "Gmail asked Archie to slow down; trying again in 2 seconds…" in heard
    assert "Gmail: fetched 100 of 120 threads…" in heard


def test_chunks_strip_quotes_and_signatures_and_carry_people(tmp_path):
    fake = FakeGmail({"t1": [ASK, REPLY]})
    home, _ = sync(fake, tmp_path=tmp_path)
    chunks = chunk_file("sources/gmail/t1.json", (home / "sources/gmail/t1.json").read_text())
    assert [c.chunk_id for c in chunks] == ["c0", "s0", "c1"]  # the first message's signature is its own chunk
    assert "Staff Eng" not in chunks[0].text and "Staff Eng" in chunks[1].text
    assert "> Hi Test" not in chunks[2].text and "wrote:" not in chunks[2].text
    assert chunks[0].label == "Email from Sarah Jones: Redis fallback (Thu Oct 1, 2:30 AM)"
    assert "sarah.j@acme.example" in chunks[0].people
    assert chunks[0].ts == "2026-10-01T09:30:00+00:00"


def test_bulk_mail_is_flagged(tmp_path):
    news = gmail_message("m5", "t5", "News <noreply@news.example>", "test@acme.example", "Weekly", "hello",
                         datetime(2026, 10, 1, tzinfo=timezone.utc), headers={"List-Unsubscribe": "<mailto:x>"})
    home, _ = sync(FakeGmail({"t5": [news]}), tmp_path=tmp_path)
    assert read_raw(home / "sources/gmail/t5.json")["messages"][0]["bulk"] is True


def test_gmail_chunker_is_registered_without_explicit_import():
    import subprocess
    import sys

    code = ("from archie.index.chunk import chunk_file; import json;"
            "d={'messages':[{'from_email':'a@b.c','body':'hello','date':'2026-10-01T00:00:00+00:00','to':[],'cc':[]}]};"
            "print(len(chunk_file('sources/gmail/t.json', json.dumps(d))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "1", out.stderr


def test_enabled_connectors_reads_config():
    from archie.connectors.registry import enabled_connectors

    assert enabled_connectors({"connectors": {}}) == []
    assert [c.name for c in enabled_connectors({"connectors": {"gmail": {"enabled": True}}})] == ["gmail"]


def test_rate_limits_are_retried_with_backoff(tmp_path):
    from archie.connectors import google_retry
    from tests.support.fake_google import Flaky

    sleeps = []
    google_retry.SLEEP = sleeps.append
    try:
        assert google_retry.execute(Flaky(type("R", (), {"execute": lambda self: {"ok": 1}})(), fails=2)) == {"ok": 1}
        assert google_retry.execute(Flaky(type("R", (), {"execute": lambda self: {"ok": 2}})(), 1, 429)) == {"ok": 2}
    finally:
        google_retry.SLEEP = __import__("time").sleep
    assert sleeps == [2, 4, 2]


def test_rate_limit_gives_up_eventually():
    import pytest

    from archie.connectors import google_retry
    from tests.support.fake_google import Flaky, HttpErrorRate

    google_retry.SLEEP = lambda s: None
    try:
        with pytest.raises(HttpErrorRate):
            google_retry.execute(Flaky(None, fails=99))
    finally:
        google_retry.SLEEP = __import__("time").sleep


def test_each_email_excerpt_records_its_sender():
    from archie.connectors.gmail import chunk_thread
    from tests.support.raw import addr, msg

    data = {"id": "t1", "subject": "Hi", "messages": [
        msg("m1", "Sarah.J@Acme.example", "Sarah", [addr("test@acme.example")], "2026-10-01T09:00:00+00:00", "hi"),
        msg("m2", "test@acme.example", "Test", [addr("sarah.j@acme.example")], "2026-10-01T10:00:00+00:00", "hey",
            from_me=True)]}
    assert [c.sender for c in chunk_thread("sources/gmail/t1.json", data)] == ["sarah.j@acme.example",
                                                                             "test@acme.example"]


SIG_CRLF = "Thanks,\r\n  Workperson\r\n\r\n-- \r\nWorkperson Acorn\r\nDirector of Engineering\r\n781-526-7220"


def test_crlf_and_lf_mail_strip_the_same():
    from archie.connectors.gmail import clean_body, split_body

    assert clean_body(SIG_CRLF) == clean_body(SIG_CRLF.replace("\r\n", "\n")) == "Thanks,\n  Workperson"
    assert split_body(SIG_CRLF)[1] == "Workperson Acorn\nDirector of Engineering\n781-526-7220"


def test_signature_is_its_own_chunk():
    from archie.connectors.gmail import chunk_thread

    data = {"id": "t1", "messages": [{"id": "m1", "from_email": "workperson@ow.example", "from_name": "Workperson Acorn",
                                      "to": [{"email": "test@acme.example", "name": "Test"}], "cc": [],
                                      "date": "2026-09-22T20:16:16+00:00", "subject": "Incoming Offer",
                                      "body": SIG_CRLF, "from_me": False}]}
    chunks = chunk_thread("sources/gmail/t1.json", data)
    assert [c.chunk_id for c in chunks] == ["c0", "s0"]
    sig = chunks[1]
    assert sig.text == "Workperson Acorn\nDirector of Engineering\n781-526-7220"
    assert sig.people == ["workperson@ow.example"] and sig.sender == "workperson@ow.example"
    assert sig.label.startswith("Signature of Workperson Acorn (")
    assert "Director of Engineering" not in chunks[0].text


def test_quoted_signatures_make_no_chunk():
    from archie.connectors.gmail import split_body

    body = "Thanks Workperson!\r\n\r\nOn Tue, Sep 22, 2026 at 1:16 PM Workperson Acorn <w@ow.example> wrote:\r\n> --\r\n> Workperson Acorn\r\n> Director"
    assert split_body(body) == ("Thanks Workperson!", "")


def test_an_original_message_after_the_signature_stays_out_of_it():
    from archie.connectors.gmail import split_body

    body = ("Sounds good.\n-- \nWorkperson Acorn\nDirector of Engineering\n\n-----Original Message-----\n"
            "From: Test\nMy private reply.")
    assert split_body(body) == ("Sounds good.", "Workperson Acorn\nDirector of Engineering")

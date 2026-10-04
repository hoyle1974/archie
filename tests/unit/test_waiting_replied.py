"""A waiting item whose other person has since written in the thread says so, and is named
by their display name, not their address (review 2026-10-04: HeadphonesRUs replied with a
setup guide, the item still read "waiting on contact@headphonesrus.example")."""

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import (
    Loop,
    _counterpart,
    load_loops,
    refresh_waiting,
    save_loop,
)
from archie.derive.people import PeopleDirectory
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import TEST, by_schema, make_ctx, question, understood
from tests.support.raw import addr, msg, write_thread

ME = "test@acme.example"
STATUS = "contact@headphonesrus.example"


def waiting(ctx, created="2026-09-30T20:00:00+00:00", name=STATUS):
    meta = {"loop_id": "l1", "kind": "waiting_on", "status": "open", "counterpart": STATUS, "counterpart_name": name,
            "summary": "Troubleshoot new earbud pairing issue", "created_at": created, "due": None,
            "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))


def thread(ctx, *later):
    first = msg("m0", STATUS, "HeadphonesRUs", [addr(ME)], "2026-09-29T09:00:00+00:00", "Here's your order.",
                to_me=True)
    mine = msg("m1", ME, "Test", [addr(STATUS)], "2026-09-30T20:00:00+00:00", "One stays red. Any thoughts?",
               from_me=True)
    write_thread(ctx.home, "t1", [first, mine, *later])


def test_counterpart_name_comes_from_the_thread_when_the_to_header_has_none():
    data = {"messages": [msg("m0", STATUS, "HeadphonesRUs", [addr(ME)], "2026-09-29T09:00:00+00:00", "x", to_me=True)]}
    mine = msg("m1", ME, "Test", [addr(STATUS)], "2026-09-30T20:00:00+00:00", "y", from_me=True)
    assert _counterpart(mine, TEST, PeopleDirectory(), data) == (STATUS, "HeadphonesRUs")


def test_a_reply_after_the_item_opened_is_marked_and_the_name_filled(tmp_path):
    ctx = make_ctx(tmp_path)
    waiting(ctx)
    thread(ctx, msg("m2", STATUS, "HeadphonesRUs", [addr(ME)], "2026-10-01T04:47:00+00:00", "Try the setup guide.",
                    to_me=True))
    refresh_waiting(ctx)
    m = load_loops(ctx.home)[0].meta
    assert m["replied"] == "2026-10-01T04:47:00+00:00"
    assert m["counterpart_name"] == "HeadphonesRUs"
    assert m["status"] == "open"  # closing stays the user's call
    out = render(ask(ctx, "what am I waiting on?"))
    assert "HeadphonesRUs replied Sep 30" in out  # 4:47 UTC is the evening before, Pacific
    assert "contact@headphonesrus.example" not in out.split("Sources")[0]


def test_my_own_later_message_is_not_a_reply(tmp_path):
    ctx = make_ctx(tmp_path)
    waiting(ctx, name="HeadphonesRUs")
    thread(ctx, msg("m2", ME, "Test", [addr(STATUS)], "2026-10-01T04:47:00+00:00", "Bump?", from_me=True))
    refresh_waiting(ctx)
    assert "replied" not in load_loops(ctx.home)[0].meta


ROUTE = understood(question("next"))


def test_next_with_only_a_young_waiting_item_names_it_instead_of_nothing_open(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE)))
    waiting(ctx, name="HeadphonesRUs")
    thread(ctx)
    out = render(ask(ctx, "what should I work on next?"))
    assert "nothing open" not in out.lower()
    assert "Nothing for you to do. You're waiting on HeadphonesRUs" in out


def test_next_shows_a_reply_as_your_turn(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE)))
    waiting(ctx, name="HeadphonesRUs")
    thread(ctx, msg("m2", STATUS, "HeadphonesRUs", [addr(ME)], "2026-10-01T04:47:00+00:00", "Try the setup guide.",
                    to_me=True))
    refresh_waiting(ctx)
    out = render(ask(ctx, "what should I work on next?"))
    assert "They replied" in out and "Troubleshoot new earbud pairing issue" in out
    assert "nothing open" not in out.lower()

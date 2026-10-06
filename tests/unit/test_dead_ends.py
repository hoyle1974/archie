"""Intents mark where they gave up on what was asked (`Answer.dead_end`), so ask can dig further
(spec: dig-deeper §1.1). Correct empty results are not dead ends."""

from archie.ask.intents.brief import brief_intent
from archie.ask.intents.loops import loops_intent
from archie.ask.intents.search import search_intent
from archie.ask.intents.who import who_intent
from archie.ask.render import render
from archie.derive.people import derive_people
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

EMPTY = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
TEST = "test@acme.example"


def _with_sarah(ctx):
    path = write_thread(ctx.home, "t1", [msg("m1", "sarah@acme.example", "Sarah Jones", [addr(TEST)],
                                             "2026-09-28T16:00:00+00:00", "Lunch on Friday?", to_me=True)])
    derive_people(ctx, [path])
    ctx.index.sync()


def test_brief_for_only_unknown_people_says_so_and_picks_no_meeting(tmp_path):
    ctx = make_ctx(tmp_path)
    a = brief_intent(ctx, "prep me for that meeting", {**EMPTY, "people": ["Workpersontwo"]})
    assert render(a) == ("I don't know anyone called Workpersontwo.\n"
                         "You have no meetings to prepare for in the next two weeks.")
    assert a.dead_end == "no file on anyone called Workpersontwo"


def test_brief_with_no_meeting_at_all_is_a_dead_end(tmp_path):
    ctx = make_ctx(tmp_path)
    a = brief_intent(ctx, "prep me for my next meeting", dict(EMPTY))
    assert a.plain == "You have no meetings to prepare for in the next two weeks."
    assert a.dead_end == "no meeting matched"


def test_brief_with_an_ambiguous_name_is_not_a_dead_end(tmp_path):
    ctx = make_ctx(tmp_path)
    paths = [write_thread(ctx.home, f"t{i}", [msg(f"m{i}", email, name, [addr(TEST)], "2026-09-28T16:00:00+00:00",
                                                  "hello there", to_me=True)])
             for i, (email, name) in enumerate([("alex@a.example", "Alex Rivera"), ("alex@b.example", "Alex Kim")])]
    derive_people(ctx, paths)
    a = brief_intent(ctx, "prep me to meet Alex", {**EMPTY, "people": ["Alex"]})
    assert "I know more than one Alex" in render(a)
    assert a.dead_end is None


def test_who_unknown_and_nothing_found_is_a_dead_end(tmp_path):
    ctx = make_ctx(tmp_path)
    a = who_intent(ctx, "who is Zebulon?", {**EMPTY, "people": ["Zebulon"]})
    assert render(a) == "I didn't recognise anyone called Zebulon, and a search found nothing about it."
    assert a.dead_end == "no one called Zebulon, and search found nothing"


def test_search_with_no_hits_is_a_dead_end(tmp_path):
    ctx = make_ctx(tmp_path)
    a = search_intent(ctx, "the quarterly roadmap", dict(EMPTY))
    assert a.nothing_found and a.dead_end == "search found nothing"


def test_nothing_open_is_a_true_answer_not_a_dead_end(tmp_path):
    ctx = make_ctx(tmp_path)
    _with_sarah(ctx)
    a = loops_intent(ctx, "what do I owe people?", dict(EMPTY))
    assert a.dead_end is None

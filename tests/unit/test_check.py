"""The answer check and the handoff to dig (spec: dig-deeper §1.2–1.4)."""

import json

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.llm.backend import FakeBackend, LLMError
from tests.support.fixtures import by_schema, make_ctx, part, question, understood
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def seed(ctx):
    write_thread(ctx.home, "t1", [msg("m1", "workperson@acme.example", "Workperson Acorn", [addr(TEST)],
                                      "2026-10-01T22:00:00+00:00", "Thanks for pinging Workpersontwo about onboarding!",
                                      subject="Onboarding", to_me=True)])
    ctx.index.sync()


def _cite_first(system, user, shape, tier):
    return {"summary": [{"text": "Workperson thanked you for pinging Workpersontwo.",
                         "citations": [{"ref": 1, "quote": "Thanks for pinging Workpersontwo"}]}], "sections": []}


def _names(fb):
    return [c["shape"].name for c in fb.calls]


def _log(ctx):
    return json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1])


def test_a_helpful_answer_is_checked_once_and_shown(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("search", topic="onboarding")), answer=_cite_first,
                               answer_check={"helpful": True}))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    out = render(ask(ctx, "what about onboarding?"))
    assert out.startswith("Workperson thanked you")
    assert _names(fb) == ["understand", "answer", "answer_check"]
    assert _log(ctx)["check"] == "helpful" and "dig" not in _log(ctx)


def test_an_unhelpful_answer_is_dug_and_replaced(tmp_path):
    first = {"summary": [], "sections": []}
    steps = [{"do": "search", "arg": "Workpersontwo"}, {"do": "answer"}]
    fb = FakeBackend(by_schema(understand=understood(question("search", topic="Workpersontwo")),
                               answer=lambda s, u, sh, t: _cite_first(s, u, sh, t) if "first answer missed" in u else first,
                               answer_check={"helpful": False, "missing": "who Workpersontwo is"},
                               dig_step=lambda *a: steps.pop(0)))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    out = render(ask(ctx, "what about Workpersontwo?"))
    assert out.startswith("Workperson thanked you for pinging Workpersontwo.")
    assert out.endswith("I looked further: 1 search.")
    log = _log(ctx)
    assert log["check"] == "unhelpful" and log["dig"]["improved"] and log["dig"]["actions"] == ["search: Workpersontwo"]


def test_progress_names_each_phase_so_a_slow_backend_shows_where_it_is(tmp_path):
    first = {"summary": [], "sections": []}
    steps = [{"do": "search", "arg": "Workpersontwo"}, {"do": "answer"}]
    fb = FakeBackend(by_schema(understand=understood(question("search", topic="Workpersontwo")),
                               answer=lambda s, u, sh, t: _cite_first(s, u, sh, t) if "first answer missed" in u else first,
                               answer_check={"helpful": False, "missing": "who Workpersontwo is"},
                               dig_step=lambda *a: steps.pop(0)))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    heard = []
    ask(ctx, "what about Workpersontwo?", progress=heard.append)
    assert heard == ["Understanding the question…", "Writing the first answer…", "Checking the answer…",
                     "Looking further… deciding what to check next (round 1 of 5)",
                     "Looking further… searching “Workpersontwo”",
                     "Looking further… deciding what to check next (round 2 of 5)",
                     "Looking further… writing the answer"]


def test_a_dead_end_digs_without_a_check(tmp_path):
    steps = [{"do": "search", "arg": "Workpersontwo"}, {"do": "answer"}]
    fb = FakeBackend(by_schema(understand=understood(question("brief", people=["Workpersontwo"])), answer=_cite_first,
                               dig_step=lambda *a: steps.pop(0)))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    ask(ctx, "prep me for the meeting with Workpersontwo")
    assert "answer_check" not in _names(fb)
    assert _log(ctx)["dead_end"] == "no file on anyone called Workpersontwo"


def test_a_dig_that_finds_nothing_keeps_the_first_answer_and_says_so(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("brief", people=["Zebulon"])),
                               dig_step={"do": "search", "arg": "Zebulon"}))
    ctx = make_ctx(tmp_path, fb, dig=True)
    ctx.config["ask"]["dig"]["rounds"] = 1
    out = render(ask(ctx, "prep me to meet Zebulon"))
    assert out == ("I don't know anyone called Zebulon.\nYou have no meetings to prepare for in the next two weeks.\n\n"
                   "I looked further (1 search) and found nothing more.")
    assert _log(ctx)["dig"]["improved"] is False


def test_no_check_for_tellings_quick_questions_or_when_switched_off(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(part("tell", fact="other")),
                               loop_update={"loops": [], "until": None, "reason": None, "one": False}))
    ctx = make_ctx(tmp_path, fb, dig=True)
    ask(ctx, "I will meet with Workpersontwo next week")
    ask(ctx, "what's next?")  # quick route: no model call at all
    assert _names(fb) == ["understand"]
    fb2 = FakeBackend(by_schema(understand=understood(question("brief", people=["Workpersontwo"]))))
    ctx2 = make_ctx(tmp_path / "off", fb2, dig=False)
    ask(ctx2, "prep me for the meeting with Workpersontwo")
    assert _names(fb2) == ["understand"]


def test_no_check_while_asking_which_one(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("who", people=["Alex"]))))
    ctx = make_ctx(tmp_path, fb, dig=True)
    from archie.derive.people import derive_people
    paths = [write_thread(ctx.home, f"t{i}", [msg(f"m{i}", e, n, [addr(TEST)], "2026-09-30T18:00:00+00:00", "hello",
                                                  to_me=True)])
             for i, (e, n) in enumerate([("alex@a.example", "Alex Rivera"), ("alex@b.example", "Alex Kim")])]
    derive_people(ctx, paths)
    ctx.index.sync()
    fb.replies = by_schema(understand=understood(question("who", people=["Alex"])), answer_check={"helpful": True})
    out = render(ask(ctx, "who is Alex?"))
    assert "Which Alex" in out


def test_a_failed_check_leaves_the_first_answer(tmp_path):
    def check(*a):
        raise LLMError("budget used up")

    fb = FakeBackend(by_schema(understand=understood(question("search", topic="onboarding")), answer=_cite_first,
                               answer_check=check))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    assert render(ask(ctx, "what about onboarding?")).startswith("Workperson thanked you")
    assert "check" not in _log(ctx)


def test_every_cited_point_dropped_is_a_dead_end(tmp_path):
    bad = {"summary": [{"text": "Made up.", "citations": [{"ref": 1, "quote": "words that are not there"}]}],
           "sections": []}
    fb = FakeBackend(by_schema(understand=understood(question("search", topic="onboarding")), answer=bad,
                               dig_step={"do": "answer"}))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    ask(ctx, "what about onboarding?")
    assert _log(ctx)["dead_end"] == "every cited point was dropped"
    assert "answer_check" not in _names(fb)

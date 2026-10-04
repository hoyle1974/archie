import pytest

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.ask.which import ask_which, match, resolve
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, make_ctx, part, understood
from tests.unit.test_actions import loop, seed

LABELS = ["Workpersonthree's pizza instructions", "Workpersonfour's IEP form"]
QUESTION = "Which one: Workpersonthree's pizza instructions or Workpersonfour's IEP form?"


def test_the_question_lists_the_options():
    assert ask_which(LABELS) == QUESTION
    assert ask_which(["A", "B", "C"]) == "Which one: A, B or C?"


@pytest.mark.parametrize("said, want", [
    ("2", 1), ("#1", 0), ("number 2", 1), ("the first one", 0), ("second", 1), ("the last one", 1),
    ("Workpersonthree's", 0), ("workpersonfour", 1), ("the IEP one", 1), ("Workpersonthree's pizza", 0),
    ("3", None), ("the pizza or the form", None), ("what's on tomorrow?", None), ("", None),
])
def test_a_reply_is_matched_by_number_ordinal_or_a_word_only_one_option_has(said, want):
    assert match(said, LABELS) == want


def test_a_word_in_both_options_picks_neither():
    assert match("the pizza one", ["Workpersonthree's pizza order", "Workpersonfour's pizza money"]) is None


def picker(loops, one):
    return {"loops": loops, "until": None, "reason": None, "one": one}


def test_the_picker_asks_which_one_when_one_item_is_meant_and_two_fit(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="she's done with it", action="loop_done")),
        loop_update=picker([1, 2], True))))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    answer = ask(ctx, "she's done with it")
    assert render(answer) == QUESTION
    assert [loop(ctx, n)["status"] for n in (1, 2)] == ["open", "open"]
    assert answer.pending["kind"] == "loops" and [o["id"] for o in answer.pending["options"]] == ["loop-1", "loop-2"]


def test_several_items_meant_are_all_applied(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="both are done", action="loop_done")),
        loop_update=picker([1, 2], False))))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    assert render(ask(ctx, "both are done")) == "Marked done: Workpersonthree, pizza instructions; Workpersonfour, IEP form."


def test_resolving_applies_the_original_action_to_the_chosen_item_only(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    pending = {"kind": "loops", "action": "snooze", "until": "2026-10-05", "reason": None,
               "options": [{"label": LABELS[0], "id": "loop-1"}, {"label": LABELS[1], "id": "loop-2"}]}
    assert render(resolve(ctx, pending, 1)) == "Snoozed until Monday: Workpersonfour, IEP form."
    assert loop(ctx, 1)["status"] == "open" and loop(ctx, 2)["snoozed_until"] == "2026-10-05"


def test_an_item_closed_meanwhile_is_left_alone(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx, ("Workpersonthree", "Pizza instructions", "done"), ("Workpersonfour", "IEP form", "open"))
    pending = {"kind": "loops", "action": "dismiss", "until": None, "reason": None,
               "options": [{"label": LABELS[0], "id": "loop-1"}, {"label": LABELS[1], "id": "loop-2"}]}
    assert render(resolve(ctx, pending, 0)) == "That one is already closed, so I left it alone."
    assert loop(ctx, 1)["status"] == "done"

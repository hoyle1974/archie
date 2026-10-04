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


def two_items(tmp_path, model):
    ctx = make_ctx(tmp_path, FakeBackend(model))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    return ctx


def asks_which(rest=None):
    def model(system, user, shape, tier):
        if shape.name == "loop_update":
            return picker([1, 2], True)
        if shape.name == "understand" and user.rstrip().endswith("she's done with it"):
            return understood(part("instruct", text="she's done with it", action="loop_done"))
        return rest(system, user, shape, tier) if rest else understood(part("question", intent="help"))
    return model


def test_the_next_message_answers_the_question_with_no_model_call(tmp_path):
    from archie.ask import conversation

    ctx = two_items(tmp_path, asks_which())
    ask(ctx, "she's done with it")
    assert conversation.load(ctx.home)[-1]["pending"]["options"][0]["id"] == "loop-1"
    calls = len(ctx.backend.calls)
    assert render(ask(ctx, "Workpersonthree's")) == "Marked done: Workpersonthree, pizza instructions."
    assert len(ctx.backend.calls) == calls
    assert [loop(ctx, n)["status"] for n in (1, 2)] == ["done", "open"]
    assert conversation.load(ctx.home)[-1]["pending"] is None


def test_after_thirty_quiet_minutes_the_question_is_gone(tmp_path):
    from datetime import timedelta

    ctx = two_items(tmp_path, asks_which())
    ask(ctx, "she's done with it")
    ctx.now += timedelta(minutes=31)
    ask(ctx, "Workpersonthree's")
    assert [loop(ctx, n)["status"] for n in (1, 2)] == ["open", "open"]


def test_any_other_message_drops_the_question(tmp_path):
    ctx = two_items(tmp_path, asks_which())
    ask(ctx, "she's done with it")
    ask(ctx, "what can you do?")
    ask(ctx, "Workpersonthree's")
    assert [loop(ctx, n)["status"] for n in (1, 2)] == ["open", "open"]


def test_the_understanding_call_sees_the_question_and_can_answer_it(tmp_path):
    seen = []

    def rest(system, user, shape, tier):
        seen.append(user)
        return understood(part("answer", text="the school one", options=[2]))

    ctx = two_items(tmp_path, asks_which(rest))
    ask(ctx, "she's done with it")
    assert render(ask(ctx, "the school one")) == "Marked done: Workpersonfour, IEP form."
    assert "Archie just asked: " + QUESTION in seen[0] and "2. Workpersonfour's IEP form" in seen[0]


def test_an_answer_to_no_listed_option_is_not_applied(tmp_path):
    def rest(system, user, shape, tier):
        if shape.name == "answer":
            return {"summary": [], "sections": []}
        return understood(part("answer", text="the other thing", options=[5]))

    ctx = two_items(tmp_path, asks_which(rest))
    ask(ctx, "she's done with it")
    ask(ctx, "the other thing")
    assert [loop(ctx, n)["status"] for n in (1, 2)] == ["open", "open"]


def test_unclear_between_two_open_questions_asks_and_applies_the_answer(tmp_path):
    from archie.derive.dedupe import save_questions
    from archie.store.files import Note, write_note

    heard = []
    model = by_schema(understand=understood(part("unclear", text="it's my plumber", fact="person", options=[1, 2])),
                      remember=lambda s, u, sh, t: (heard.append(u), {"people": []})[1])
    ctx = make_ctx(tmp_path, FakeBackend(model))
    for i, who in enumerate(("a@b.co", "c@d.co"), 1):
        write_note(ctx.home / f"people/p{i}.md", Note(meta={"entity_id": f"p{i}", "name": who, "aliases": [who]}, body=""))
    save_questions(ctx.home, [
        {"id": f"q{i}", "kind": "who_is", "person": f"p{i}", "status": "open",
         "text": f"Who is {who}? Tell me, e.g. \"{who} is my plumber\".", "asked_at": "2026-10-01T00:00:00+00:00"}
        for i, who in enumerate(("a@b.co", "c@d.co"), 1)])
    assert render(ask(ctx, "it's my plumber")) == "Which one: a@b.co or c@d.co?"
    ask(ctx, "the second one")
    assert heard == ["c@d.co: it's my plumber"]


def test_a_yes_shaped_reply_to_which_one_never_answers_another_question(tmp_path):
    from archie.derive.dedupe import save_questions

    def rest(system, user, shape, tier):
        return understood(part("answer", text="yeah, Workpersonthree's", options=[1]))

    ctx = two_items(tmp_path, asks_which(rest))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"), ("Bob", "Old thing", "maybe_done"))
    save_questions(ctx.home, [{"id": "q1", "kind": "loop_done", "loop": "loop-3", "status": "open",
                               "text": "Did you finish: Old thing (Bob)?", "asked_at": "2026-10-01T00:00:00+00:00"}])
    ask(ctx, "she's done with it")
    assert render(ask(ctx, "yeah, Workpersonthree's")) == "Marked done: Workpersonthree, pizza instructions."
    assert [loop(ctx, n)["status"] for n in (1, 2, 3)] == ["done", "open", "maybe_done"]


def test_yes_no_questions_are_not_offered_as_which_one_options():
    from archie.ask.understand import checked

    qs = [{"id": "q1", "kind": "loop_done", "text": "Did you finish: A?"},
          {"id": "q2", "kind": "who_is", "text": "Who is a@b.co?"}, {"id": "q3", "kind": "who_is", "text": "Who is c@d.co?"}]
    [p] = checked([{"kind": "unclear", "text": "finished that", "options": [1, 2, 3]}], "finished that", [], qs)
    assert p.options == [2, 3]


def test_a_snooze_with_no_date_asks_until_when_before_which_one(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="snooze hers", action="loop_snooze")),
        loop_update=picker([1, 2], True))))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    answer = ask(ctx, "snooze hers")
    assert render(answer).startswith("Until when?") and answer.pending is None


def test_options_are_unique_and_in_list_order(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="she's done with it", action="loop_done")),
        loop_update=picker([2, 1, 2], True))))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    assert render(ask(ctx, "she's done with it")) == QUESTION


def test_a_snooze_through_which_one_keeps_the_original_date(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="snooze hers till Monday", action="loop_snooze", until="2026-10-05")),
        loop_update=picker([1, 2], True))))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    ask(ctx, "snooze hers till Monday")
    assert render(ask(ctx, "2")) == "Snoozed until Monday: Workpersonfour, IEP form."

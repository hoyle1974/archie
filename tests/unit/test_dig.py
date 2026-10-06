"""The dig loop (spec: dig-deeper §2): the model picks a step, code runs it, the packet grows,
and the answer is written and verified from it. Rounds and money are capped."""

from archie.ask.dig import dig
from archie.llm.backend import FakeBackend, LLMError
from archie.store.files import Note, write_note
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def seed(ctx):
    write_thread(ctx.home, "t1", [msg("m1", "workperson@acme.example", "Workperson Acorn", [addr(TEST)],
                                      "2026-10-01T22:00:00+00:00", "Thanks for pinging Workpersontwo about onboarding!",
                                      subject="Onboarding", to_me=True)])
    write_note(ctx.home / "meetings/2026/2026-09-23-workpersontwo.md", Note(meta={
        "event_id": "e1", "title": "Test Testerson & Workpersontwo Birch", "start": "2026-09-23T16:00:00+00:00",
        "end": "2026-09-23T16:30:00+00:00", "status": "scheduled", "type": "event", "attendees": [],
        "attendee_names": []}, body="## My notes\n\nVideo call with Workpersontwo Birch about the new job.\n"))
    write_note(ctx.home / "meetings/2026/2026-09-24-swim.md", Note(meta={
        "event_id": "e2", "title": "Goodspouse - Swimming", "start": "2026-09-24T16:30:00+00:00",
        "end": "2026-09-24T17:30:00+00:00", "status": "cancelled", "type": "event", "attendees": [],
        "attendee_names": []}, body="## My notes\n\n"))
    ctx.index.sync()


def cite(quote):
    """An answer citing whichever source holds `quote`."""
    import re

    def answer(system, user, shape, tier):
        ref = next(int(n) for n, body in re.findall(r'<source n="(\d+)"[^>]*>(.*?)</source>', user, re.S)
                   if quote in body)
        return {"summary": [{"text": "Found it.", "citations": [{"ref": ref, "quote": quote}]}], "sections": []}
    return answer


def scripted(steps, answer=None):
    plan = list(steps)
    return FakeBackend(by_schema(dig_step=lambda *a: plan.pop(0) if plan else {"do": "answer"},
                                 answer=answer or {"summary": [], "sections": []}))


def _notebooks(fb):
    return [c["user"] for c in fb.calls if c["shape"].name == "dig_step"]


def test_steps_run_until_answer_and_the_answer_is_verified(tmp_path):
    fb = scripted([{"do": "search", "arg": "Workpersontwo"}, {"do": "answer", "new_person": "Workpersontwo Birch"}],
                  answer=cite("Thanks for pinging Workpersontwo"))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    r = dig(ctx, "who is Workpersontwo?", "no file on anyone called Workpersontwo")
    assert r.actions == ["search: Workpersontwo"] and r.new_person == "Workpersontwo Birch"
    assert r.answer.summary[0].citations[0].quote == "Thanks for pinging Workpersontwo"
    assert r.answer.notes == ["I looked further: 1 search."]
    assert "Thanks for pinging Workpersontwo" in _notebooks(fb)[1]  # the result reached the next round


def test_rounds_are_capped(tmp_path):
    fb = scripted([{"do": "search", "arg": f"q{i}"} for i in range(10)])
    ctx = make_ctx(tmp_path, fb, dig=True)
    ctx.config["ask"]["dig"]["rounds"] = 3
    r = dig(ctx, "q", "nothing")
    assert len(r.actions) == 3 and len(_notebooks(fb)) == 3


def test_money_is_capped_per_question(tmp_path):
    class Budget:
        session_usd = 0.0

    class Pricey(FakeBackend):
        budget = Budget()

        def complete(self, *a, **k):
            self.budget.session_usd += 0.1
            return super().complete(*a, **k)

    plan = [{"do": "search", "arg": f"q{i}"} for i in range(10)]
    fb = Pricey(by_schema(dig_step=lambda *a: plan.pop(0), answer={"summary": [], "sections": []}))
    ctx = make_ctx(tmp_path, fb, dig=True)
    ctx.config["ask"]["dig"]["max_usd"] = 0.25
    r = dig(ctx, "q", "nothing")
    assert len(r.actions) == 2  # a third round could pass 0.25 with the answer still to write
    assert r.usd > 0


def test_repeats_unknown_steps_and_bad_paths_are_refused(tmp_path):
    fb = scripted([{"do": "search", "arg": "Workpersontwo"}, {"do": "search", "arg": "workpersontwo"},
                   {"do": None, "arg": "x"}, {"do": "open", "arg": "../secrets.json"},
                   {"do": "open", "arg": "sources/gmail/never-shown.json"}, {"do": "person", "arg": ""}])
    ctx = make_ctx(tmp_path, fb, dig=True)
    ctx.config["ask"]["dig"]["rounds"] = 6
    seed(ctx)
    r = dig(ctx, "q", "nothing")
    assert r.actions[0] == "search: Workpersontwo" and all(a.startswith("refused") for a in r.actions[1:])
    last = _notebooks(fb)[-1]
    assert "(refused: already done)" in last and "(refused: not a step on the list)" in last
    assert last.count("(refused: only paths shown in results") == 2
    assert r.actions[-1] == "refused: person: "  # the sixth step: no model call reads its result


def test_a_path_shown_in_a_result_can_be_opened(tmp_path):
    fb = scripted([{"do": "search", "arg": "Workpersontwo onboarding"}, {"do": "open", "arg": "sources/gmail/t1.json"}])
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    r = dig(ctx, "q", "nothing")
    assert r.actions == ["search: Workpersontwo onboarding", "open: sources/gmail/t1.json"]


def test_calendar_lists_personal_and_cancelled_entries(tmp_path):
    fb = scripted([{"do": "calendar", "arg": "2026-09-20 2026-09-30"}], answer=cite("Video call with Workpersontwo Birch"))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    r = dig(ctx, "q", "nothing")
    note = _notebooks(fb)[1]
    assert "Test Testerson & Workpersontwo Birch · with no one else (personal)" in note
    assert "Goodspouse - Swimming · with no one else (cancelled, personal)" in note
    assert r.answer is not None and r.answer.notes == ["I looked further: 1 calendar check."]


def test_person_lookup_says_when_there_is_no_file(tmp_path):
    fb = scripted([{"do": "person", "arg": "Workpersontwo"}])
    ctx = make_ctx(tmp_path, fb, dig=True)
    dig(ctx, "q", "nothing")
    assert "(no people file on anyone called Workpersontwo)" in _notebooks(fb)[1]


def test_a_model_error_mid_dig_answers_from_what_it_has(tmp_path):
    calls = iter([{"do": "search", "arg": "Workpersontwo"}])

    def step(*a):
        try:
            return next(calls)
        except StopIteration:
            raise LLMError("Gemini had a server error") from None

    fb = FakeBackend(by_schema(dig_step=step, answer=cite("Thanks for pinging Workpersontwo")))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    r = dig(ctx, "q", "nothing")
    assert r.actions == ["search: Workpersontwo"] and r.answer is not None


def test_nothing_gathered_means_no_answer_call(tmp_path):
    fb = scripted([{"do": "search", "arg": "zzz"}])
    ctx = make_ctx(tmp_path, fb, dig=True)
    r = dig(ctx, "q", "nothing")
    assert r.answer is None and r.nothing_more() == "I looked further (1 search) and found nothing more."
    assert "answer" not in [c["shape"].name for c in fb.calls]


def test_no_claim_to_have_looked_when_no_step_ran(tmp_path):
    def step(*a):
        raise LLMError("Gemini had a server error")

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(dig_step=step)), dig=True)
    assert dig(ctx, "q", "nothing").nothing_more() is None
    ctx2 = make_ctx(tmp_path / "refused", scripted([{"do": "open", "arg": "../x"}]), dig=True)
    assert dig(ctx2, "q", "nothing").nothing_more() is None


def test_progress_says_what_it_is_doing(tmp_path):
    fb = scripted([{"do": "search", "arg": "Workpersontwo"}, {"do": "calendar", "arg": "2026-09-20 2026-09-30"}])
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx)
    heard = []
    dig(ctx, "q", "nothing", progress=heard.append)
    assert heard[:2] == ["Looking further… searching “Workpersontwo”", "Looking further… checking your calendar Sep 20 to Sep 30"]


def test_only_the_users_own_files_are_searched(tmp_path):
    fb = scripted([{"do": "web", "arg": "Workpersontwo Birch"}])
    ctx = make_ctx(tmp_path, fb, dig=True)
    r = dig(ctx, "q", "nothing")
    assert r.actions == ["refused: web: Workpersontwo Birch"]
    assert "web" not in fb.calls[0]["system"].lower()

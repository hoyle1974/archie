from datetime import date

from archie.ask.actions import when
from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import by_schema, make_ctx, part, understood


def seed(ctx, *items):
    for i, (who, summary, status) in enumerate(items, 1):
        meta = {"loop_id": f"loop-{i}", "kind": "waiting_on", "status": status, "counterpart": f"p{i}@x.example",
                "counterpart_name": who, "summary": summary, "created_at": "2026-09-28T16:30:00+00:00",
                "due": None, "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [],
                "closed_by": None}
        save_loop(ctx.home, Loop(f"loop-{i}", f"loops/2026/loop-{i}.md", Note(meta=meta, body="")))


def loop(ctx, n):
    return next(lp for lp in load_loops(ctx.home) if lp.loop_id == f"loop-{n}").meta


def test_when_says_a_weekday_this_week_and_a_short_date_after():
    today = date(2026, 10, 1)
    assert when("2026-10-05", today) == "Monday"
    assert when("2026-10-01", today) == "today"
    assert when("2026-10-02", today) == "tomorrow"
    assert when("2026-10-20", today) == "Tue, Oct 20"


def test_snooze_takes_the_date_from_the_understanding_call_and_confirms_from_code(tmp_path):
    seen = []

    def pick(system, user, shape, tier):
        seen.append(system)
        return {"loops": [1], "until": None, "reason": None}

    instruct = part("instruct", text="I'll give them till Monday", action="loop_snooze", until="2026-10-05")
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(instruct), loop_update=pick)))
    seed(ctx, ("HeadphonesRUs", "Earbud pairing", "open"))
    assert render(ask(ctx, "I'll give them till Monday")) == "Snoozed until Monday: HeadphonesRUs, earbud pairing."
    assert loop(ctx, 1)["status"] == "snoozed" and loop(ctx, 1)["snoozed_until"] == "2026-10-05"
    assert "snooze" in seen[0]


def test_snooze_with_no_date_asks_and_changes_nothing(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="snooze the earbuds one", action="loop_snooze")),
        loop_update={"loops": [1], "until": None, "reason": None})))
    seed(ctx, ("HeadphonesRUs", "Earbud pairing", "open"))
    assert render(ask(ctx, "snooze the earbuds one")) == 'Until when? Say e.g. "snooze that till Monday".'
    assert loop(ctx, 1)["status"] == "open"


def test_a_bad_date_from_the_picker_asks_too(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="snooze it a while", action="loop_snooze")),
        loop_update={"loops": [1], "until": "a while", "reason": None})))
    seed(ctx, ("HeadphonesRUs", "Earbud pairing", "open"))
    assert render(ask(ctx, "snooze it a while")).startswith("Until when?")
    assert loop(ctx, 1)["status"] == "open"


def test_a_pick_outside_the_list_changes_nothing(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="done with that", action="loop_done")),
        loop_update={"loops": [7], "until": None, "reason": None})))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"))
    out = render(ask(ctx, "done with that"))
    assert out.startswith("I couldn't tell which item you meant.") and "Pizza instructions" in out
    assert loop(ctx, 1)["status"] == "open"


def test_done_names_who_and_what(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="Workpersonthree's done with the pizza", action="loop_done")),
        loop_update={"loops": [1], "until": None, "reason": None})))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "open"))
    assert render(ask(ctx, "Workpersonthree's done with the pizza")) == "Marked done: Workpersonthree, pizza instructions."
    assert loop(ctx, 1)["status"] == "done" and loop(ctx, 2)["status"] == "open"


def test_reopen_picks_only_from_closed_items(tmp_path):
    lists = []

    def pick(system, user, shape, tier):
        lists.append(user)
        return {"loops": [1], "until": None, "reason": None}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="reopen the IEP form", action="loop_reopen")), loop_update=pick)))
    seed(ctx, ("Workpersonthree", "Pizza instructions", "open"), ("Workpersonfour", "IEP form", "done"))
    assert render(ask(ctx, "reopen the IEP form")) == "Reopened: Workpersonfour, IEP form."
    assert "IEP form" in lists[0] and "Pizza" not in lists[0]
    assert loop(ctx, 2)["status"] == "open"


def test_meeting_type_goes_to_the_correction_code(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="the sync is a standup", action="meeting_type")),
        correct={"kind": "meeting_type", "meeting": "sync", "meeting_type": "bogus", "alias": None,
                 "person": None, "role": None})))
    assert render(ask(ctx, "the sync is a standup")).startswith("Which kind of meeting is it")


def told(ctx):
    from archie.ask.tell import TOLD

    path = ctx.home / TOLD
    return path.read_text() if path.exists() else ""


def gaps(ctx):
    import json

    lines = (ctx.home / "logs/usage.jsonl").read_text().splitlines()
    return json.loads(lines[-1]).get("gaps", [])


def test_a_wish_is_saved_and_said_plainly(tmp_path):
    msg = "only show work stuff on weekdays"
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", action="none", wanted="filter Today by day")))))
    assert render(ask(ctx, msg)) == "I can't filter Today by day yet. I've saved that you want it."
    assert f'"{msg}" → can\'t do this yet' in told(ctx)
    assert gaps(ctx) == [msg]


def test_a_long_or_missing_wish_quotes_the_words(tmp_path):
    msg = "only show work stuff on weekdays"
    quoted = "I can't do “only show work stuff on weekdays” yet. I've saved that you want it."
    cases = (("one two three four five six seven eight nine ten eleven twelve thirteen", "none"),
             ("filter Today\nby day", "none"), (None, "none"), (None, None), (None, "fly_to_mars"))
    for i, (wanted, action) in enumerate(cases):
        ctx = make_ctx(tmp_path / str(i),
                       FakeBackend(by_schema(understand=understood(part("instruct", action=action, wanted=wanted)))))
        assert render(ask(ctx, msg)) == quoted, (wanted, action)
        assert gaps(ctx) == [msg]


def test_send_is_refused_logged_as_a_gap_and_not_saved_as_a_wish(tmp_path):
    msg = "email Workpersonthree about Friday"
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("instruct", action="send")))))
    assert render(ask(ctx, msg)) == "I can't send anything; I only read."
    assert told(ctx) == "" and gaps(ctx) == [msg]


def test_a_telling_beside_a_send_is_saved_and_said_first(tmp_path):
    msg = "email Workpersonthree that the pizza's picked up"
    tell = part("tell", text="the pizza's picked up", fact="other")
    send = part("instruct", text="email Workpersonthree", action="send")
    for i, parts in enumerate(([tell, send], [send, tell])):
        ctx = make_ctx(tmp_path / str(i), FakeBackend(by_schema(understand=understood(*parts))))
        out = render(ask(ctx, msg))
        assert out == "I saved that the pizza's picked up. I can't send anything; I only read."
        assert '"the pizza\'s picked up" → saved only' in told(ctx) and "email Workpersonthree\"" not in told(ctx)
        assert "archie ask" not in out


def test_an_action_the_model_made_up_still_gets_the_cant_yet_reply(tmp_path):
    msg = "remind me at 5"
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=f"PART instruct\ntext: {msg}\naction: set_reminder")))
    assert render(ask(ctx, msg)) == f"I can't do “{msg}” yet. I've saved that you want it."


def test_names_and_I_keep_their_capitals_in_code_written_replies(tmp_path):
    from archie.store.files import write_note

    send = part("instruct", text="email her", action="send")
    for i, (said, want) in enumerate((("Workpersonthree picked up the pizza.", "I saved that Workpersonthree picked up the pizza."),
                                      ("I'm out Friday.", "I saved that I'm out Friday."),
                                      ("The pizza's picked up.", "I saved that the pizza's picked up."))):
        ctx = make_ctx(tmp_path / str(i), FakeBackend(by_schema(
            understand=understood(part("tell", text=said, fact="other"), send))))
        write_note(ctx.home / "people/workpersonthree.md", Note(meta={"entity_id": "workpersonthree", "name": "Workpersonthree", "aliases": []}, body=""))
        assert render(ask(ctx, f"{said} email her")) == f"{want} I can't send anything; I only read."


def test_a_loop_summary_that_starts_with_a_name_keeps_it(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="done with it", action="loop_done")),
        loop_update={"loops": [1], "until": None, "reason": None})))
    seed(ctx, ("Workpersonthree", "Workpersonthree's pizza instructions", "open"))
    assert render(ask(ctx, "done with it")) == "Marked done: Workpersonthree, Workpersonthree's pizza instructions."


def test_a_snoozed_item_can_still_be_marked_done(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="the earbud one is done", action="loop_done")),
        loop_update={"loops": [1], "until": None, "reason": None})))
    seed(ctx, ("HeadphonesRUs", "Earbud pairing", "snoozed"))
    meta_path = ctx.home / "loops/2026/loop-1.md"
    meta_path.write_text(meta_path.read_text().replace("snoozed_until: null", "snoozed_until: '2026-10-09'"))
    assert render(ask(ctx, "the earbud one is done")) == "Marked done: HeadphonesRUs, earbud pairing."
    assert loop(ctx, 1)["status"] == "done"


def test_a_snooze_date_in_the_past_asks_again(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="snooze it till Monday", action="loop_snooze", until="2026-09-28")),
        loop_update={"loops": [1], "until": None, "reason": None})))
    seed(ctx, ("HeadphonesRUs", "Earbud pairing", "open"))
    assert render(ask(ctx, "snooze it till Monday")).startswith("Until when?")
    assert loop(ctx, 1)["status"] == "open"


def test_the_picker_sees_which_item_the_user_meant(tmp_path):
    seen = []
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="snooze that till Monday", action="loop_snooze",
                                   target="the earbud one", until="2026-10-05")),
        loop_update=lambda s, u, sh, t: (seen.append(u), {"loops": [1], "until": None, "reason": None})[1])))
    seed(ctx, ("HeadphonesRUs", "Earbud pairing", "open"))
    ask(ctx, "snooze that till Monday, the earbud one")
    assert "They mean: the earbud one" in seen[0]


def test_an_other_answer_beside_a_send_is_said_first_too(tmp_path):
    from archie.derive.dedupe import save_questions

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(
        part("instruct", text="email them back", action="send"),
        part("answer", text="it's the school newsletter", question=1, fact="other")))))
    save_questions(ctx.home, [{"id": "q1", "kind": "who_is", "person": "x", "status": "open",
                               "text": "Who is news@school.example? Tell me, e.g. \"news@school.example is my plumber\".",
                               "asked_at": "2026-10-01T00:00:00+00:00"}])
    assert render(ask(ctx, "it's the school newsletter, email them back")) == \
        "I saved that it's the school newsletter. I can't send anything; I only read."


def test_a_person_telling_beside_a_wish_keeps_both_replies_telling_first(tmp_path):
    sam = {"people": [{"name": "Sam", "relationship": "neighbor", "role": None, "pronouns": None, "identity": None,
                       "avoid": [], "other_names": [], "statement": "Sam is my neighbor."}]}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", text="text me a reminder", action="none", wanted="send you reminders"),
                              part("tell", text="Sam is my neighbor.", fact="person")),
        remember=sam)))
    out = render(ask(ctx, "text me a reminder. Sam is my neighbor."))
    assert out.startswith("Got it. I'll remember:\n  • Sam, new: “Sam is my neighbor.”")
    assert out.endswith("\n\nI can't send you reminders yet. I've saved that you want it.")

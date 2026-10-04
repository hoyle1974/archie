from archie.derive.audit import audit, resolve_answered
from archie.derive.dedupe import open_questions, save_questions
from archie.derive.loops import Loop, load_loops, save_loop
from archie.store.files import Note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

ME = "test@acme.example"
STATUS = "contact@headphonesrus.example"
NUDGE = "Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow up?"


def waiting(ctx, lid="l1", summary="Earbud pairing", created="2026-09-28T09:00:00+00:00", status="open",
            snoozed_until=None, kind="waiting_on", thread="t1"):
    meta = {"loop_id": lid, "kind": kind, "status": status, "counterpart": STATUS, "counterpart_name": "HeadphonesRUs",
            "summary": summary, "created_at": created, "due": None, "snoozed_until": snoozed_until, "thread": thread,
            "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop(lid, f"loops/2026/{lid}.md", Note(meta=meta, body="")))


def thread(ctx, *later, tid="t1"):
    asked = msg("m0", ME, "Test", [addr(STATUS)], "2026-09-28T09:00:00+00:00", "Any fix for the pairing?",
                from_me=True)
    write_thread(ctx.home, tid, [asked, *later])


def nudges(ctx):
    return [q["text"] for q in open_questions(ctx.home) if q["kind"] == "waiting_nudge"]


def test_three_days_with_no_reply_is_a_nudge(tmp_path):
    ctx = make_ctx(tmp_path)
    waiting(ctx)
    thread(ctx)
    audit(ctx)
    assert nudges(ctx) == [NUDGE]


def test_too_young_snoozed_or_not_waiting_is_no_nudge(tmp_path):
    for i, kwargs in enumerate(({"created": "2026-09-29T09:00:00+00:00"}, {"status": "snoozed", "snoozed_until": "2026-10-03"},
                                {"kind": "asked_of_me"}, {"status": "done"}, {"status": "maybe_done"})):
        ctx = make_ctx(tmp_path / str(i))
        waiting(ctx, **kwargs)
        thread(ctx)
        audit(ctx)
        assert nudges(ctx) == [], kwargs


def test_a_reply_from_them_means_no_nudge_but_my_own_message_does_not_count(tmp_path):
    ctx = make_ctx(tmp_path / "mine")
    waiting(ctx)
    thread(ctx, msg("m1", ME, "Test", [addr(STATUS)], "2026-09-29T09:00:00+00:00", "Bump?", from_me=True))
    audit(ctx)
    assert nudges(ctx) == [NUDGE]
    for i, sender in enumerate((STATUS, "support@headphonesrus.example")):
        ctx = make_ctx(tmp_path / str(i))
        waiting(ctx)
        thread(ctx, msg("m1", sender, "Status", [addr(ME)], "2026-09-29T09:00:00+00:00", "Try a reset.", to_me=True))
        audit(ctx)
        assert nudges(ctx) == [], sender


def test_a_reply_clears_an_open_nudge_without_a_model(tmp_path):
    ctx = make_ctx(tmp_path)
    waiting(ctx)
    thread(ctx)
    audit(ctx)
    thread(ctx, msg("m1", STATUS, "Status", [addr(ME)], "2026-09-30T09:00:00+00:00", "Try a reset.", to_me=True))
    resolve_answered(ctx)
    assert nudges(ctx) == []


def test_closing_the_item_clears_the_nudge(tmp_path):
    ctx = make_ctx(tmp_path)
    waiting(ctx)
    thread(ctx)
    audit(ctx)
    lp = load_loops(ctx.home)[0]
    lp.meta["status"] = "dismissed"
    save_loop(ctx.home, lp)
    resolve_answered(ctx)
    assert nudges(ctx) == []


def test_a_nudge_comes_back_only_after_a_snooze_ends_with_no_reply(tmp_path):
    from datetime import timedelta

    ctx = make_ctx(tmp_path)
    waiting(ctx)
    thread(ctx)
    audit(ctx)
    [q] = [q for q in open_questions(ctx.home) if q["kind"] == "waiting_nudge"]
    q.update(status="answered")
    save_questions(ctx.home, [q])
    lp = load_loops(ctx.home)[0]
    lp.meta.update(status="snoozed", snoozed_until="2026-10-04")
    save_loop(ctx.home, lp)
    audit(ctx)
    assert nudges(ctx) == []
    ctx.now += timedelta(days=3)
    audit(ctx)
    assert nudges(ctx) == ["Still waiting on HeadphonesRUs about the earbud pairing (6 days). Want to follow up?"]


def test_long_summaries_are_quoted_and_one_day_is_singular(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.config["nudges"]["after_days"] = 1
    waiting(ctx, summary="Troubleshoot new earbud pairing issue", created="2026-09-30T08:00:00+00:00")
    thread(ctx)
    audit(ctx)
    assert nudges(ctx) == ["Still waiting on HeadphonesRUs about “Troubleshoot new earbud pairing issue” (1 day). "
                           "Want to follow up?"]


def test_nudges_rank_after_stale_items_and_before_who_is(tmp_path):
    from archie.derive.audit import PRIORITY

    assert PRIORITY["loop_stale"] < PRIORITY["waiting_nudge"] < PRIORITY["who_is"]


def nudged(tmp_path, reply):
    from archie.llm.backend import FakeBackend
    from tests.support.fixtures import by_schema, understood

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(reply))))
    waiting(ctx)
    thread(ctx)
    audit(ctx)
    return ctx


def answered(ctx):
    from archie.derive.dedupe import load_questions

    return [q["status"] for q in load_questions(ctx.home) if q["kind"] == "waiting_nudge"]


def test_giving_them_till_monday_snoozes_the_item(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    said = "I'll give them till Monday"
    ctx = nudged(tmp_path, part("answer", text=said, question=1, action="loop_snooze", until="2026-10-05"))
    assert render(ask(ctx, said)) == "Snoozed until Monday: HeadphonesRUs, earbud pairing."
    assert load_loops(ctx.home)[0].meta["snoozed_until"] == "2026-10-05" and answered(ctx) == ["answered"]
    assert f'"{said}" → Snoozed until Monday: HeadphonesRUs, earbud pairing.' in (ctx.home / "journal/told.md").read_text()


def test_done_and_drop_it_close_the_item(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    for action, want, status in (("loop_done", "Marked done", "done"), ("loop_dismiss", "Dismissed", "dismissed")):
        ctx = nudged(tmp_path / action, part("answer", text="they replied", question=1, action=action))
        assert render(ask(ctx, "they replied")) == f"{want}: HeadphonesRUs, earbud pairing."
        assert load_loops(ctx.home)[0].meta["status"] == status and nudges(ctx) == []


def test_yes_ill_follow_up_waits_another_three_days(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    for i, action in enumerate(("nudge_snooze", None)):
        ctx = nudged(tmp_path / str(i), part("answer", text="yes, I'll follow up", question=1, action=action))
        assert render(ask(ctx, "yes, I'll follow up")) == "Snoozed until Sunday: HeadphonesRUs, earbud pairing."
        assert load_loops(ctx.home)[0].meta["snoozed_until"] == "2026-10-04"


def test_a_snooze_answer_with_no_future_date_asks_and_changes_nothing(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    for i, until in enumerate((None, "2026-09-28")):
        ctx = nudged(tmp_path / str(i), part("answer", text="give them a while", question=1, action="loop_snooze",
                                             until=until))
        assert render(ask(ctx, "give them a while")).startswith("Until when?")
        assert load_loops(ctx.home)[0].meta["status"] == "open" and answered(ctx) == ["open"]


def test_a_plain_yes_to_a_nudge_goes_to_the_understanding_call(tmp_path):
    from archie.ask.pipeline import ask
    from tests.support.fixtures import part

    ctx = nudged(tmp_path, part("answer", text="yes", question=1))
    ask(ctx, "yes")
    assert [c["shape"].name for c in ctx.backend.calls] == ["understand"]
    assert load_loops(ctx.home)[0].meta["snoozed_until"] == "2026-10-04"


def test_follow_up_as_an_instruction_uses_the_one_open_nudge(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    ctx = nudged(tmp_path / "one", part("instruct", text="I'll follow up with them", action="nudge_snooze"))
    assert render(ask(ctx, "I'll follow up with them")) == "Snoozed until Sunday: HeadphonesRUs, earbud pairing."
    ctx = make_ctx(tmp_path / "none", ctx.backend)
    assert render(ask(ctx, "I'll follow up with them")) == "There's nothing to follow up on right now."


def test_follow_up_with_two_open_nudges_asks_which(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    ctx = nudged(tmp_path, part("instruct", text="I'll follow up with them", action="nudge_snooze"))
    waiting(ctx, lid="l2", summary="Refund", thread="t2")
    thread(ctx, tid="t2")
    audit(ctx)
    assert render(ask(ctx, "I'll follow up with them")) == \
        "Which one: HeadphonesRUs about the earbud pairing or HeadphonesRUs about the refund?"
    assert render(ask(ctx, "the refund one")) == "Snoozed until Sunday: HeadphonesRUs, refund."


def test_yes_to_a_nudge_with_a_did_you_finish_question_open_leaves_the_other_item_alone(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    ctx = nudged(tmp_path, part("answer", text="yes, I'll follow up", question=1, action="nudge_snooze"))
    waiting(ctx, lid="l2", summary="Send invoice", kind="asked_of_me", status="maybe_done", thread="t2")
    audit(ctx)
    assert [q["kind"] for q in open_questions(ctx.home)] == ["waiting_nudge", "loop_done"]
    assert render(ask(ctx, "yes, I'll follow up")) == "Snoozed until Sunday: HeadphonesRUs, earbud pairing."
    assert [c["shape"].name for c in ctx.backend.calls] == ["understand"]
    assert {lp.loop_id: lp.meta["status"] for lp in load_loops(ctx.home)} == {"l1": "snoozed", "l2": "maybe_done"}


def test_which_one_keeps_the_action_the_user_asked_for(tmp_path):
    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from tests.support.fixtures import part

    for action, until, want in (("loop_dismiss", None, "Dismissed: HeadphonesRUs, refund."),
                                ("loop_snooze", "2026-10-09", "Snoozed until Fri, Oct 9: HeadphonesRUs, refund.")):
        ctx = nudged(tmp_path / action, part("unclear", text="drop it", options=[1, 2], action=action, until=until))
        waiting(ctx, lid="l2", summary="Refund", thread="t2")
        thread(ctx, tid="t2")
        audit(ctx)
        assert render(ask(ctx, "drop it")).startswith("Which one:")
        assert render(ask(ctx, "the refund one")) == want


def test_short_imperative_summaries_are_quoted(tmp_path):
    ctx = make_ctx(tmp_path)
    waiting(ctx, summary="Review the patch")
    thread(ctx)
    audit(ctx)
    assert nudges(ctx) == ["Still waiting on HeadphonesRUs about “Review the patch” (3 days). Want to follow up?"]

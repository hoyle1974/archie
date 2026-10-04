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

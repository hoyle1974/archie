"""Vignette R (docs/VIGNETTES.md): nudges."""

from datetime import timedelta

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.audit import MAX_OPEN, audit
from archie.derive.dedupe import open_questions
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from archie.tui.feed import build_feed
from tests.support.fixtures import make_ctx, part, question, understood
from tests.support.raw import addr, msg, write_thread

ME = "test@acme.example"
STATUS = "contact@headphonesrus.example"
NUDGE = "Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow up?"
REPLIES = {
    "I'll give them till Monday": {"action": "loop_snooze", "until": "2026-10-05"},
    "Yes, I'll follow up": {"action": "nudge_snooze"},
}


def model(system, user, shape, tier):
    if shape.name == "understand":
        said = user.rsplit("Message:", 1)[-1].strip()
        if said in REPLIES:
            return understood(part("answer", text=said, question=1, **REPLIES[said]))
        return understood(question("search"))
    return {"summary": [], "sections": []}


def seeded(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(model))
    meta = {"loop_id": "l1", "kind": "waiting_on", "status": "open", "counterpart": STATUS,
            "counterpart_name": "HeadphonesRUs", "summary": "Earbud pairing", "created_at": "2026-09-28T09:00:00+00:00",
            "due": None, "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    write_thread(ctx.home, "t1", [asked()])
    audit(ctx)
    return ctx


def asked():
    return msg("m0", ME, "Test", [addr(STATUS)], "2026-09-28T09:00:00+00:00", "Any fix for the pairing?",
               from_me=True)


def nudges(ctx):
    return [q["text"] for q in open_questions(ctx.home) if q["kind"] == "waiting_nudge"]


def test_R_today_shows_the_nudge_and_a_snooze_quiets_it(tmp_path):
    ctx = seeded(tmp_path)
    assert NUDGE in build_feed(ctx)

    assert render(ask(ctx, "I'll give them till Monday")) == "Snoozed until Monday: HeadphonesRUs, earbud pairing."
    assert load_loops(ctx.home)[0].meta["snoozed_until"] == "2026-10-05"
    audit(ctx)
    assert nudges(ctx) == [] and NUDGE not in build_feed(ctx)


def test_R_a_reply_from_status_audio_clears_the_nudge(tmp_path):
    ctx = seeded(tmp_path)
    reply = msg("m1", STATUS, "HeadphonesRUs", [addr(ME)], "2026-09-30T09:00:00+00:00", "Try a reset.", to_me=True)
    write_thread(ctx.home, "t1", [asked(), reply])
    audit(ctx)
    assert nudges(ctx) == []


def test_R_following_up_waits_three_more_days_then_asks_again(tmp_path):
    ctx = seeded(tmp_path)
    assert render(ask(ctx, "Yes, I'll follow up")) == "Snoozed until Sunday: HeadphonesRUs, earbud pairing."
    audit(ctx)
    assert nudges(ctx) == []

    ctx.now += timedelta(days=3)
    audit(ctx)
    assert nudges(ctx) == ["Still waiting on HeadphonesRUs about the earbud pairing (6 days). Want to follow up?"]


def test_R_nudges_count_toward_the_open_question_limit(tmp_path):
    ctx = seeded(tmp_path)
    for i in range(2, MAX_OPEN + 3):
        meta = {**load_loops(ctx.home)[0].meta, "loop_id": f"l{i}", "thread": f"t{i}", "summary": f"Order {i}"}
        save_loop(ctx.home, Loop(f"l{i}", f"loops/2026/l{i}.md", Note(meta=meta, body="")))
        write_thread(ctx.home, f"t{i}", [asked()])
    audit(ctx)
    assert len(open_questions(ctx.home)) == MAX_OPEN and NUDGE in nudges(ctx)

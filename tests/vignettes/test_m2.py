"""M2 vignettes (docs/VIGNETTES.md): A (standard, 1:1), B, C (email), H, J, L."""

from datetime import datetime, timezone

import pytest

from archie.briefings.build import build_briefing
from archie.briefings.schedule import tick
from archie.derive.loops import load_loops
from archie.derive.meetings import find_meeting
from archie.store.files import Note, read_note, write_note
from tests.vignettes.week import ME, SARAH, Week, at, mail


def test_A_standard_briefing(tmp_path):
    w = Week(tmp_path)
    sent = []
    w.ctx.now = datetime(2026, 10, 1, 20, 45, tzinfo=timezone.utc)
    tick(w.ctx, notify=lambda t, m: sent.append(t))
    assert sent == ["Design Review: Auth Redesign"]
    out = w.ask("prep me for the design review")
    assert out.splitlines()[0] == "2:00 PM · Design Review: Auth Redesign · 45 min"
    assert "Alex Rivera · last talked Thu Oct 1" in out  # the 10 AM standup already happened
    assert "Priya Sharma · last talked Thu Oct 1" in out
    assert "Alex Rivera: Can you review my fallback logic by today" in out  # code-computed open item
    seen = w.llm.saw("answer")
    assert "Attached Doc: Auth_Migration_Draft" in seen  # the attached doc reached the model
    assert "Merged PR 412" in seen and "auth migration is paused" in seen


def _edit_doc_after_morning_batch(w):
    sent = []
    tick(w.ctx, notify=lambda t, m: sent.append(t))  # 8:02 AM morning batch builds today's briefings
    f = w.drive.files_by_id["d2"]
    f["modifiedTime"] = "2026-10-01T20:15:00Z"  # Alex edits the doc at 1:15 PM
    w.drive.texts["d2"] += " Adds a Redis cluster section."
    w.drive.changes_list = [{"fileId": "d2", "removed": False, "file": f}]
    w.ctx.now = datetime(2026, 10, 1, 20, 45, tzinfo=timezone.utc)  # 1:45 PM, T-15
    w.sync()
    return sent


def test_A_edit_after_morning_batch_rebuilds_once(tmp_path):
    w = Week(tmp_path)
    sent = _edit_doc_after_morning_batch(w)
    assert tick(w.ctx, notify=lambda t, m: sent.append(t)) == ["Design Review: Auth Redesign"]
    w.ctx.now = datetime(2026, 10, 1, 20, 46, tzinfo=timezone.utc)
    assert tick(w.ctx, notify=lambda t, m: sent.append(t)) == []  # nothing changed since: no second rebuild
    assert sent == ["Design Review: Auth Redesign"]  # one notification
    assert "Adds a Redis cluster section." in w.llm.saw("answer")


@pytest.mark.xfail(strict=True, reason="DESIGN §7.3: briefings don't show 'refreshed' yet")
def test_A_rebuilt_briefing_says_when_it_was_built_and_refreshed(tmp_path):
    w = Week(tmp_path)
    _edit_doc_after_morning_batch(w)
    tick(w.ctx, notify=lambda t, m: None)
    out = w.ask("prep me for the design review")
    assert "Built 8:02 AM, refreshed 1:45 PM." in out


def test_A_one_on_one_briefing_uses_last_1on1_notes(tmp_path):
    w = Week(tmp_path)
    m = find_meeting(w.ctx.home, "oneonone_20261001T230000Z")
    assert m.meta["type"] == "one_on_one"
    w.ctx.index.sync()
    b = build_briefing(w.ctx, m)
    from archie.ask.render import render

    out = render(b.answer)
    assert "4:00 PM · Alex / Test 1:1 · 30 min" == out.splitlines()[0]
    seen = w.llm.saw("answer")
    assert "The previous 1:1 was Sep 24." in seen
    assert "Alex will draft the fallback design." in seen  # last 1:1's notes reached the model


def test_B_who_is_priya(tmp_path):
    w = Week(tmp_path)
    out = w.ask("who is Priya?")
    assert "Priya Sharma" in out and "Last talked: Wed Sep 30" in out
    assert "2 email threads together" in out
    assert "Event: Design Review" not in out.split("Recent", 1)[1].split("\n\n", 1)[0]  # future meeting isn't history
    assert "auth migration is paused" in w.llm.saw("answer")


def _glance(out: str) -> str:
    return out.split("At a glance", 1)[1].split("\n\n", 1)[0] if "At a glance" in out else ""


def test_B_full_name_and_email_find_the_same_person(tmp_path):
    w = Week(tmp_path)
    for q in ("who is Priya?", "who is Priya Sharma?", "who is priya@acme.example?"):
        assert _glance(w.ask(q)).splitlines()[1].strip() == "Priya Sharma", q


def test_B_name_with_initial_finds_the_person(tmp_path):
    w = Week(tmp_path)
    assert _glance(w.ask("who is Priya S.?")).splitlines()[1].strip() == "Priya Sharma"


def test_B_possessive_question_finds_the_person(tmp_path):
    w = Week(tmp_path)
    for q in ("what is Priya's role?", "what is Priyas role?", "what is priyas role"):
        assert _glance(w.ask(q)).splitlines()[1].strip() == "Priya Sharma", q


def test_B_unknown_or_misspelled_name_gets_a_search_answer(tmp_path):
    w = Week(tmp_path)
    out = w.ask("who is Priyaa?")
    assert out.startswith("I didn't recognise anyone called Priyaa, so I searched everything instead.")
    assert "answer" in w.llm.calls  # the answer came from search
    out = w.ask("what is Zed's role?")
    assert "anyone called role" not in out and "anyone called Zed's" not in out
    assert out.startswith("I didn't recognise anyone called Zed")


def test_B_ambiguous_name_gets_a_question_not_a_guess(tmp_path):
    w = Week(tmp_path)
    write_note(w.ctx.home / "people/alex_chen.md",
               Note(meta={"entity_id": "alex_chen", "name": "Alex Chen", "aliases": ["alex.chen@other.example"],
                          "org": "other.example", "status": "active"}, body="## My notes\n\n"))
    out = w.ask("who is Alex?")
    assert out.startswith("Which Alex?")
    assert "Alex Rivera" in out and "Alex Chen" in out
    assert "At a glance" not in out


def test_C_open_loops_from_email_and_closure_by_reply(tmp_path):
    w = Week(tmp_path)
    out = w.ask("what do I owe people?")
    assert "can you review the Redis fallback patch before Friday" in out.lower() or "Redis fallback patch" in out
    assert "Q4 capacity numbers" in out
    assert "Ten things" not in out  # newsletter never became a loop
    waiting = w.ask("what am I waiting on?")
    assert "SSO launch date" in waiting
    w.add_message("t_sarah", mail("s2", "t_sarah", f"Test Testerson <{ME}>", f"Sarah Jones <{SARAH}>",
                                  "Re: Redis fallback", "Reviewed and approved the patch.", at(1, 16)), "501")
    w.ctx.now = datetime(2026, 10, 1, 16, 30, tzinfo=timezone.utc)
    w.sync()
    sarah = [lp for lp in load_loops(w.ctx.home) if lp.meta["counterpart"] == "sarah_jones"]
    assert sarah and all(lp.meta["status"] == "done" for lp in sarah)
    assert sarah[0].meta["closed_by"]["quote"] == "Reviewed and approved the patch."


def test_C_user_can_close_and_snooze(tmp_path):
    w = Week(tmp_path)
    assert "Marked done" in w.ask("done with the capacity numbers")
    ken = [lp for lp in load_loops(w.ctx.home) if lp.meta["counterpart"] == "ken_ito"]
    assert ken[0].meta["status"] == "done"


def test_H_notes_after_the_meeting(tmp_path):
    w = Week(tmp_path)
    w.ctx.now = datetime(2026, 10, 1, 21, 50, tzinfo=timezone.utc)
    out = w.ask("notes from the design review: Redis approved. Alex to add circuit breaker. "
                "I need to update the runbook by next Wed.")
    assert "Saved your notes to Design Review: Auth Redesign" in out
    kinds = {lp.meta["summary"]: lp.meta for lp in load_loops(w.ctx.home)}
    assert kinds["update the runbook by next Wed"]["kind"] == "i_promised"
    assert kinds["update the runbook by next Wed"]["due"] == "2026-10-07"  # "next Wed" from Thu Oct 1
    assert "[you] update the runbook by next Wed (due Wed, Oct 7)" in out
    assert kinds["add circuit breaker"]["kind"] == "waiting_on"
    assert kinds["add circuit breaker"]["counterpart"] == "alex_rivera"
    note = read_note(w.ctx.home / find_meeting(w.ctx.home, "review").rel_path)
    assert "Redis approved." in note.body


def test_J_history_before_replying(tmp_path):
    w = Week(tmp_path)
    out = w.ask("what's my history with Ken?")
    assert "Ken Ito" in out and "Q4 capacity numbers" in out


@pytest.mark.xfail(strict=True, reason="VIGNETTES J: `who` doesn't list open loops with the person yet")
def test_J_history_shows_open_items_both_ways(tmp_path):
    w = Week(tmp_path)
    out = w.ask("what's my history with Ken?")
    assert "Open between you" in out
    assert "I'll send you the Q4 capacity numbers by Monday" in out.split("Open between you", 1)[1]


def test_L_someone_new(tmp_path):
    w = Week(tmp_path)
    dossier = read_note(w.ctx.home / "people/dana_kim.md").meta
    assert dossier["status"] == "stub" and dossier["org"] == "partner.example"
    w.ctx.now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    out = w.ask("prep me for the partner sync")
    assert "Dana Kim · New: no history yet (partner.example)" in out

"""Vignette V (docs/VIGNETTES.md): getting ready for people, not a meeting."""

from datetime import datetime, timezone

from tests.vignettes.variants import variants
from tests.vignettes.week import Week

AFTER_THE_WEEK = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)  # every fixture meeting is over


def test_V_people_with_no_meeting_get_a_people_briefing(tmp_path):
    w = Week(tmp_path)
    w.ctx.now = AFTER_THE_WEEK
    for q in variants("I'm meeting Sarah, Ken and Priya next week. Prep me for it?"):
        out = w.ask(q)
        assert "no upcoming meetings" not in out.lower()
        assert out.startswith("There's nothing on your calendar with Sarah, Ken and Priya")
        assert "Sarah Jones" in out and "Ken Ito" in out and "Priya Sharma · Product Manager, Auth" in out
        assert "• Sarah Jones: Hi Test, can you review the Redis fallback patch before Friday ·" in out  # open item
        seen = w.llm.saw("answer")
        assert "auth migration is paused" in seen  # Priya's own mail reached the model
        assert "Q4 capacity numbers" in seen


def test_V_a_misspelt_name_is_matched_and_said(tmp_path):
    w = Week(tmp_path)
    w.ctx.now = AFTER_THE_WEEK
    out = w.ask("prep me to meet Sarah and Prya next week")
    assert "I took Prya to mean Priya Sharma." in out
    assert "Priya Sharma · Product Manager, Auth" in out


def test_V_someone_unknown_is_said_not_dropped(tmp_path):
    w = Week(tmp_path)
    w.ctx.now = AFTER_THE_WEEK
    out = w.ask("prep me to meet Sarah and Zebulon next week")
    assert "I don't know anyone called Zebulon." in out
    assert "Sarah Jones" in out


def test_V_a_meeting_with_them_in_the_next_two_weeks_is_briefed(tmp_path):
    w = Week(tmp_path)
    w.ctx.now = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)  # the partner sync is 3 days away
    out = w.ask("prep me for my meeting with Dana")
    assert out.splitlines()[0] == "11:00 AM · Partner sync · 30 min"


def test_V_no_meeting_soon_never_says_a_day_and_a_half(tmp_path):
    w = Week(tmp_path)
    w.ctx.now = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)
    out = w.ask("prep me for my next meeting")
    assert out.splitlines()[0] == "10:00 AM · Daily Standup · 15 min"  # two days away, still the next one

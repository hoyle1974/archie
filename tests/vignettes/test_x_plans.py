"""Vignette X (docs/VIGNETTES.md): plans I tell Archie."""

from datetime import datetime, timedelta, timezone

from tests.vignettes.week import Week

SATURDAY = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)  # Sat Oct 3, 9 AM PDT; every fixture meeting is over


def week(tmp_path) -> Week:
    w = Week(tmp_path)
    w.ctx.now = SATURDAY
    return w


def test_X_a_day_off_shows_in_the_agenda(tmp_path):
    w = week(tmp_path)
    out = w.ask("Monday is a company holiday")
    assert out == "Saved for Mon, Oct 5: “Monday is a company holiday”. I'll show it in your agenda that day."
    assert '- 2026-10-05 · "Monday is a company holiday" · said 2026-10-03' in \
        (w.ctx.home / "journal/plans.md").read_text()
    assert '"Monday is a company holiday" → plan for 2026-10-05' in (w.ctx.home / "journal/told.md").read_text()

    out = w.ask("what do I have on Monday?")
    assert out.startswith("Monday, Oct 5\n  You said: “Monday is a company holiday” (Oct 3)\n")
    assert "holiday" not in w.ask("what do I have today?")  # only on its day


def test_X_a_planned_meeting_is_shown_and_prepped(tmp_path):
    w = week(tmp_path)
    out = w.ask("I will meet with Ken next week")
    assert out == ("Saved for Mon, Oct 5 to Sun, Oct 11: “I will meet with Ken next week”. "
                   "I'll show it in your agenda then.")
    assert "· with Ken" in (w.ctx.home / "journal/plans.md").read_text()

    w.ctx.now = SATURDAY + timedelta(hours=3)  # the conversation is over; "that meeting" must come from the plan
    out = w.ask("what do I have next week?")
    assert out.startswith("Plans you told me for these days:\n  • “I will meet with Ken next week” (Oct 3)\n")
    out = w.ask("Can you prep me for that meeting?")
    assert out.startswith("You said on Oct 3: “I will meet with Ken next week”. It isn't on your calendar yet. "
                          "There's nothing on your calendar with Ken")
    assert "Ken Ito" in out and "no meetings" not in out.lower()
    assert "Q4 capacity numbers" in w.llm.saw("answer")  # Ken's thread reached the model


def test_X_a_plan_with_no_date_is_kept_but_not_placed(tmp_path):
    w = week(tmp_path)
    out = w.ask("I'm taking a day off sometime soon")
    assert out == ("Saved: “I'm taking a day off sometime soon”. "
                   "I couldn't tell which day, so it won't show in your agenda.")
    assert '- no date · "I\'m taking a day off sometime soon"' in (w.ctx.home / "journal/plans.md").read_text()


def test_X_the_reply_quotes_the_words_without_doubled_punctuation(tmp_path):
    w = week(tmp_path)
    assert w.ask("Monday is a company holiday.") == \
        "Saved for Mon, Oct 5: “Monday is a company holiday.” I'll show it in your agenda that day."

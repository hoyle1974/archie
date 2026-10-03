"""Due dates are parsed by code from the verified quote (DESIGN §6.2 step 5), never taken
from the model. Relative words resolve against when the message was written."""

from datetime import datetime, timedelta, timezone

from archie.derive.dates import due_in

PDT = timezone(timedelta(hours=-7))
MON = datetime(2026, 9, 28, 9, 30, tzinfo=PDT)
THU = datetime(2026, 10, 1, 14, 50, tzinfo=PDT)
SAT = datetime(2026, 9, 26, 10, 0, tzinfo=PDT)


def test_weekday_is_the_next_one():
    assert due_in("can you review the Redis fallback patch before Friday?", MON) == "2026-10-02"
    assert due_in("I'll send you the Q4 capacity numbers by Monday.", SAT) == "2026-09-28"


def test_same_weekday_means_next_week():
    assert due_in("send it Thursday", THU) == "2026-10-08"


def test_next_weekday_is_in_the_following_week():
    assert due_in("I need to update the runbook by next Wed", THU) == "2026-10-07"
    assert due_in("I need to update the runbook by next Wed", MON) == "2026-10-07"


def test_today_and_tomorrow():
    assert due_in("Can you review my fallback logic by today?", MON) == "2026-09-28"
    assert due_in("send it by end of day", MON) == "2026-09-28"
    assert due_in("Priya ships it tomorrow", THU) == "2026-10-02"


def test_explicit_dates():
    assert due_in("due Oct 17", MON) == "2026-10-17"
    assert due_in("by october 17", MON) == "2026-10-17"
    assert due_in("by May 5", MON) == "2027-05-05"
    assert due_in("by October 17th please", MON) == "2026-10-17"
    assert due_in("before 17 Oct", MON) == "2026-10-17"
    assert due_in("deadline 2026-10-17", MON) == "2026-10-17"
    assert due_in("can you get it to me by 10/17?", MON) == "2026-10-17"


def test_month_day_without_year_rolls_forward():
    dec = datetime(2026, 12, 20, 9, 0, tzinfo=PDT)
    assert due_in("by Jan 5", dec) == "2027-01-05"


def test_deadline_word_wins_over_other_dates():
    assert due_in("After Monday's sync, can you send it by Friday?", MON) == "2026-10-02"


def test_no_date_means_no_due():
    assert due_in("can you review the patch?", MON) is None
    assert due_in("sometime next week", MON) is None
    assert due_in("3/4 of the tests pass", MON) is None
    assert due_in("you may 5x the pool", MON) is None
    assert due_in("I sat with Alex and we wed the plans", MON) is None
    assert due_in("Feb 30", MON) is None

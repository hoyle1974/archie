import time
from datetime import UTC, datetime

import pytest

from archie.store.times import stamp, utc_iso, when


@pytest.fixture(autouse=True)
def pacific(monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


NOW = datetime(2026, 10, 4, 16, 34, tzinfo=UTC)


def test_stored_times_become_utc_and_dates_stay_dates():
    assert utc_iso("2026-10-03T10:00:00-07:00") == "2026-10-03T17:00:00+00:00"
    assert utc_iso("2026-10-03T17:00:00Z") == "2026-10-03T17:00:00+00:00"
    assert utc_iso("2026-10-03T17:00:00") == "2026-10-03T17:00:00+00:00"  # naive is UTC
    assert utc_iso("2026-10-03") == "2026-10-03"
    assert utc_iso(None) is None and utc_iso("soon") == "soon"


def test_times_are_shown_in_local_time_with_weekday():
    assert when("2026-10-02T20:26:30+00:00", NOW) == "Fri Oct 2, 1:26 PM"
    assert when("2026-10-04T11:47:24+00:00", NOW) == "Sun Oct 4, 4:47 AM"
    assert when("2026-10-03", NOW) == "Sat Oct 3"
    assert when("2023-07-17T14:47:09+00:00", NOW) == "Mon Jul 17 2023, 7:47 AM"
    assert when(None) == "" and when("soon") == ""


def test_an_answer_stamp_is_local():
    assert stamp(NOW) == "Sun, Oct 4 · 9:34 AM"

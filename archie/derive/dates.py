"""Due dates, parsed by code from a verified quote (DESIGN §6.2 step 5). The model never
supplies a date. Relative words ("Friday", "next Wed", "tomorrow") resolve against when
the message or notes were written. No date in the words means no due date."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# Any case, except "May" (capitalized only: "you may 5x the pool" isn't a date).
_MONTH = r"(?:(?i:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?|sept?(?:ember)?|" \
         r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|May)\.?"
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# Full names in any case; short forms only capitalized ("sat with", "we wed" aren't days).
_WEEKDAY = r"(?i:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|Mon|Tues?|Wed|Thu(?:rs?)?|Fri|Sat|Sun"
_DEADLINE = re.compile(r"(?i:\b(?:by|before|until|till|due|on|deadline|no later than)\s+(?:the\s+)?)$")

_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("month_day", re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")),
    ("day_month", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})")),
    ("slash", re.compile(r"\b(\d{1,2})/(\d{1,2})\b")),
    ("next_weekday", re.compile(rf"\b(?i:next)\s+({_WEEKDAY})\b")),
    ("weekday", re.compile(rf"\b({_WEEKDAY})\b")),
    ("today", re.compile(r"(?i)\b(today|tonight|end of (?:the )?day|eod)\b")),
    ("tomorrow", re.compile(r"(?i)\btomorrow\b")),
]


def _month(word: str) -> int:
    return _MONTHS.index(word.lower().rstrip(".")[:3]) + 1


def _weekday(word: str) -> int:
    w = word.lower()
    return next(i for i, d in enumerate(_DAYS) if d.startswith(w[:3]))


def _rolled(month: int, day: int, today: date) -> date | None:
    """Month and day without a year: this year, or next year if that's well in the past."""
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    if d < today - timedelta(days=60):
        d = d.replace(year=today.year + 1)
    return d


def _resolve(kind: str, m: re.Match, today: date) -> date | None:
    try:
        if kind == "iso":
            return date(int(m[1]), int(m[2]), int(m[3]))
        if kind == "month_day":
            return _rolled(_month(m[1]), int(m[2]), today)
        if kind == "day_month":
            return _rolled(_month(m[2]), int(m[1]), today)
        if kind == "slash":
            return _rolled(int(m[1]), int(m[2]), today)
    except ValueError:
        return None
    if kind == "next_weekday":  # that weekday in the following Monday-to-Sunday week
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return monday + timedelta(days=_weekday(m[1]))
    if kind == "weekday":  # the next one; said on that weekday, it means next week's
        ahead = (_weekday(m[1]) - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    if kind == "today":
        return today
    if kind == "tomorrow":
        return today + timedelta(days=1)
    return None


def due_in(text: str, written: datetime) -> str | None:
    """The due date stated in `text`, as an ISO date, or None. A date right after a
    deadline word ("by", "before", "due") wins; otherwise the first date in the text."""
    today = written.astimezone(written.tzinfo).date()
    found: list[tuple[bool, int, date]] = []
    taken: list[range] = []
    for kind, rx in _PATTERNS:
        for m in rx.finditer(text or ""):
            if any(m.start() in r for r in taken):
                continue  # "next Wed" already matched; don't match "Wed" again
            if kind == "slash" and not _DEADLINE.search(text[:m.start()]):
                continue  # "3/4 of the tests" is not a date
            d = _resolve(kind, m, today)
            if d is None:
                continue
            taken.append(range(m.start(), m.end()))
            found.append((not _DEADLINE.search(text[:m.start()]), m.start(), d))
    return min(found)[2].isoformat() if found else None

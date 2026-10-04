"""Times are stored in UTC and shown in local time.

Everything Archie writes (raw files, frontmatter, state, logs) holds ISO 8601 in UTC
(`+00:00`), so stored times compare correctly as strings and as datetimes. All-day dates
stay plain dates. Only what the user reads converts to the local timezone, here."""

from __future__ import annotations

from datetime import UTC, datetime


def _parse(ts: str | datetime | None) -> datetime | None:
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts or "")
    except ValueError:
        return None


def utc_iso(ts: str | datetime | None) -> str | None:
    """`ts` as an ISO string in UTC. A plain date (all-day) is returned as is; a naive time
    is taken as UTC. Unparseable values come back unchanged."""
    if ts is None or (isinstance(ts, str) and len(ts) <= 10):
        return ts
    d = _parse(ts)
    if d is None:
        return ts
    return (d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)).isoformat()


def when(ts: str | datetime | None, now: datetime | None = None) -> str:
    """A stored time for reading, in local time: "Fri Oct 2, 1:26 PM". A plain date shows
    no time ("Sat Oct 3"); another year shows the year ("Mon Jul 17 2023, 7:47 AM")."""
    d = _parse(ts)
    if d is None:
        return ""
    date_only = isinstance(ts, str) and len(ts) <= 10
    if not date_only:
        d = d.astimezone() if d.tzinfo else d.replace(tzinfo=UTC).astimezone()
    this_year = (now or datetime.now(UTC)).astimezone().year
    day = f"{d:%a %b} {d.day}" + ("" if d.year == this_year else f" {d.year}")
    return day if date_only else f"{day}, {d:%-I:%M %p}"


def stamp(at: datetime) -> str:
    """When an answer was given, as its first line: "Sun, Oct 4 · 9:34 AM"."""
    d = at.astimezone()
    return f"{d:%a, %b} {d.day} · {d:%-I:%M %p}"

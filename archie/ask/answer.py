"""What every intent returns: a cited summary first, then optional sections."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from archie.llm.verify import Claim, Packet


@dataclass
class Section:
    heading: str
    items: list[Claim] = field(default_factory=list)  # cited facts
    lines: list[str] = field(default_factory=list)  # code-computed lines (no citation needed)


@dataclass
class Answer:
    summary: list[Claim] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    packet: Packet = field(default_factory=Packet)
    dropped: int = 0
    plain: str | None = None  # fixed text that states no facts about sources (help, errors)
    notes: list[str] = field(default_factory=list)  # e.g. "data as of 1:45 PM"
    nothing_found: bool = False
    title: str | None = None  # a code-computed first line, e.g. "2:00 PM · Design Review · 45 min"
    pending: dict | None = None  # a "which one?" question waiting on the next message (which.py)
    at: datetime | None = None  # when Archie answered (UTC); shown in local time by render(stamp=True)
    dead_end: str | None = None  # why the intent gave up on what was asked; ask digs further (dig.py)
    markdown: str | None = None  # the part of `plain` that is Markdown from a source; the TUI draws it as such

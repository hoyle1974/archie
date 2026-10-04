"""Unambiguous, parameter-free questions are recognized by code and skip the model call."""

from __future__ import annotations

import re

QUICK = [
    (r"^(help|what can you do\??|how do i use (you|archie)\??)$", "help"),
    (r"^what (should|do) i (work on|do) (next|now)\??$|^what('s| is) next\??$", "next"),
    (r"^what (do i owe( people| anyone)?|am i waiting on|('s| is) open|are my open items)\??$", "loops"),
    (r"^what('s| is| do i have)( planned| going on| happening| on my calendar)?( for| on)? "
     r"(today|tomorrow|tonight|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\??$", "agenda"),
    (r"^what('s| is) (on )?my (calendar|schedule|agenda)( for)? ?(today|tomorrow)?\??$", "agenda"),
]


def quick_route(question: str) -> str | None:
    """Unambiguous questions with no parameters skip the model call (saves seconds)."""
    q = re.sub(r"\s+", " ", question.strip().lower())
    return next((intent for rx, intent in QUICK if re.match(rx, q)), None)

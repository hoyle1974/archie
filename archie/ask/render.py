"""Plain-text rendering: summary first, details next, [n] markers; sources on request."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.llm.verify import Claim
from archie.store.times import stamp as when_answered

NOTHING = "I couldn't find anything about that in your archive."
UNVERIFIED = "I found related material but couldn't verify a confident answer from it."
EMPTY_ANSWER = "I found related material, but none of it answers that."
UNVERIFIED_HEADING = "Not directly sourced — treat with caution:"


class _Numberer:
    def __init__(self) -> None:
        self.order: list[tuple[str, str, str]] = []

    def mark(self, claim: Claim) -> str:
        nums = []
        for c in claim.citations:
            key = (c.path, c.chunk_id, c.label)
            if key not in self.order:
                self.order.append(key)
            n = self.order.index(key) + 1
            if n not in nums:
                nums.append(n)
        return "".join(f"[{n}]" for n in nums)


def render(answer: Answer, sources: bool = False, paths: bool = False, stamp: bool = False,
          show_unverified: bool = True) -> str:
    """The answer as text. `stamp` puts when Archie answered first ("Sun, Oct 4 · 9:34 AM"),
    for what the user reads; logs and follow-up memory leave it out. `show_unverified`: the
    TUI renders that block itself, in a warning color, so it asks for the text without it."""
    body = _body(answer, sources, paths, show_unverified)
    return f"{when_answered(answer.at)}\n\n{body}" if stamp and answer.at else body


def unverified_block(answer: Answer) -> str:
    """Claims the model wrote with no verified citation, never shown as fact: labeled so the
    user, not the LLM, decides whether to trust them. Empty when there are none."""
    if not answer.unverified:
        return ""
    lines = [UNVERIFIED_HEADING]
    for u in answer.unverified:
        hint = f" (near: {', '.join(u.near)})" if u.near else " (no source given)"
        lines.append(f"  • {u.text}{hint}")
    return "\n".join(lines)


def _body(answer: Answer, sources: bool, paths: bool, show_unverified: bool = True) -> str:
    if answer.plain is not None:
        return answer.plain
    if answer.nothing_found:
        return NOTHING
    if not answer.summary and not answer.sections:
        text = UNVERIFIED if answer.unverified else EMPTY_ANSWER
        out = [answer.title, text] if answer.title else [text]
        if show_unverified and answer.unverified:
            out += ["", unverified_block(answer)]
        return "\n".join(out)
    num = _Numberer()
    out = [answer.title] if answer.title else []
    if answer.summary:
        out.append(" ".join(f"{c.text} {num.mark(c)}".strip() for c in answer.summary))
    for sec in answer.sections:
        out.append("")
        out.append(sec.heading)
        out += [f"  {line}" for line in sec.lines]
        out += [f"  • {c.text} {num.mark(c)}".rstrip() for c in sec.items]
    for note in answer.notes:
        out += ["", note]
    if show_unverified and answer.unverified:
        out += ["", unverified_block(answer)]
    if sources and num.order:
        out += ["", "Sources"]
        out += [f"  [{i}] {label}" + (f"  · {path}" if paths else "") for i, (path, chunk, label) in
                enumerate(num.order, 1)]
    return "\n".join(out)


def citations_of(answer: Answer) -> list[dict]:
    """The answer's sources, numbered exactly as render() numbers its [n] markers."""
    if answer.plain is not None or answer.nothing_found:
        return []
    num = _Numberer()
    quotes: dict[tuple[str, str, str], str] = {}
    for claim in [*answer.summary, *(c for sec in answer.sections for c in sec.items)]:
        num.mark(claim)
        for c in claim.citations:
            quotes.setdefault((c.path, c.chunk_id, c.label), c.quote)
    return [{"n": i, "file": path, "chunk": chunk, "label": label, "quote": quotes[(path, chunk, label)]}
            for i, (path, chunk, label) in enumerate(num.order, 1)]

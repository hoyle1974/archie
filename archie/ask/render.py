"""Plain-text rendering: summary first, details next, [n] markers; sources on request."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.llm.verify import Claim

NOTHING = "I couldn't find anything about that in your archive."
UNVERIFIED = ("I found related material but couldn't verify any answer against it, "
              "so I'm not showing one. Try asking more specifically.")


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


def render(answer: Answer, sources: bool = False, paths: bool = False) -> str:
    if answer.plain is not None:
        return answer.plain
    if answer.nothing_found:
        return NOTHING
    if not answer.summary and not answer.sections:
        return f"{answer.title}\n{UNVERIFIED}" if answer.title else UNVERIFIED
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
    if sources and num.order:
        out += ["", "Sources"]
        out += [f"  [{i}] {label}" + (f"  · {path}" if paths else "") for i, (path, chunk, label) in
                enumerate(num.order, 1)]
    return "\n".join(out)

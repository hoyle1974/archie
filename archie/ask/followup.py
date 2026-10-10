"""Follow-ups that need no model call (spec: understand-first §2.4): "show 2" opens a
citation from the last answer, and "really?" asks the last question again."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.render import NOTHING
from archie.store.files import read_raw

SHOW = re.compile(r"^\s*(?:show|open)(?: me)?(?: (?:source|citation))?\s*\[?(\d+)\]?\s*[.!?]?\s*$", re.I)
RECHECK = re.compile(r"^\s*(really|are you sure|you sure|is that right|is that true|double[- ]check( that)?)"
                     r"\s*[?!.]*\s*$", re.I)
CHECKED = "I checked again."
CHANGED = "This is different from my earlier answer."


def citation_number(text: str) -> int | None:
    m = SHOW.match(text or "")
    return int(m.group(1)) if m else None


def is_recheck(text: str) -> bool:
    return bool(RECHECK.match(text or ""))


FRONT_MATTER = re.compile(r"\A---\n.*?\n---[ \t]*(?:\n|\Z)", re.S)
FENCE = re.compile(r"^[ \t]*<!-- /?archie:auto -->[ \t]*(?:\n|\Z)", re.M)


def _readable(text: str) -> str:
    """The chunk without YAML front matter or archie:auto fences, which mean nothing to a reader."""
    text = FENCE.sub("", FRONT_MATTER.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _find(text: str, quote: str) -> re.Match | None:
    words = (quote or "").split()
    for some in (words, words[:8]):
        if some:
            m = re.search(r"\s+".join(map(re.escape, some)), text, re.I)
            if m:
                return m
    return None


def _around(text: str, quote: str, width: int = 200) -> str:
    """The text around the quote, cut at line breaks so headings and lists stay whole. A line
    longer than `width` is cut at a space instead."""
    text = _readable(text)
    m = _find(text, quote)
    if m is None:
        return ""
    start = text.rfind("\n", 0, max(0, m.start() - width)) + 1
    if m.start() - start > 2 * width:
        start = text.find(" ", m.start() - width, m.start()) + 1 or m.start() - width
    end = text.find("\n", min(len(text), m.end() + width))
    end = len(text) if end < 0 else end
    if end - m.end() > 2 * width:
        end = text.rfind(" ", m.end(), m.end() + width)
        end = m.end() + width if end < 0 else end
    head = "" if start == 0 else "…\n\n" if text[start - 1] == "\n" else "…"
    tail = "" if end >= len(text) else "\n\n…" if text[end] == "\n" else "…"
    return head + text[start:end].strip("\n") + tail


def show(ctx: Ctx, last: dict | None, n: int) -> Answer:
    cites = (last or {}).get("citations") or []
    if not cites:
        return Answer(plain="There's no recent answer with sources to show.")
    c = next((c for c in cites if c.get("n") == n), None)
    if c is None:
        return Answer(plain=f"The last answer has citations 1–{len(cites)}.")
    lines = [f"[{n}] {c.get('label') or c['file']}", f"“{c.get('quote', '')}”"]
    around = _around(ctx.index.chunk_text(c["file"], c["chunk"]) or "", c.get("quote", ""))
    if around:
        lines += ["", around]
    lines += ["", c["file"]]
    if c["file"].startswith("sources/claude/"):
        from pathlib import Path

        data = read_raw(ctx.home / c["file"])
        original = Path(data.get("original", "")).expanduser()
        if original.exists():
            lines.append(f"Full log: {data['original']}")
        else:
            lines.append("The full log was removed by Claude Code's 30-day cleanup; this is Archie's copy.")
    markdown = around if around and c["file"].endswith(".md") else None
    return Answer(plain="\n".join(lines), markdown=markdown)


def recheck(previous: dict, answer: Answer, new_citations: list[dict]) -> Answer:
    """Open with "I checked again.", and say so when the sources behind the answer changed
    completely, or one answer found something and the other didn't."""
    before = {c.get("file") for c in previous.get("citations") or []}
    after = {c.get("file") for c in new_citations}
    changed = bool(before) != bool(after) or bool(before and after and not before & after)
    head = f"{CHECKED} {CHANGED}" if changed else CHECKED
    if answer.nothing_found and answer.plain is None:
        answer.plain = NOTHING
    if answer.plain is not None:
        answer.plain = f"{head}\n{answer.plain}"
    else:
        answer.title = f"{head}\n{answer.title}" if answer.title else head
    return answer

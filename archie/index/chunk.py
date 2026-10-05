"""Split files into chunks for indexing (DESIGN §5.3).

Chunks are a pure function of the file's content, so the disposable index can always be
rebuilt and a citation's chunk can be recomputed from the file alone.

- Markdown: frontmatter is its own chunk, then one chunk per heading section; long
  sections are split into word windows with overlap. Offsets index into the file text.
- Raw JSON (sources/<source>/...): each connector registers a chunker that turns its
  payload into readable text. Offsets are 0 because the text is extracted, not a slice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable

CHUNKER_VERSION = "3"
MAX_WORDS = 280  # ≈ 360 tokens, inside bge-small's 512-token window
OVERLAP_WORDS = 40


@dataclass
class Chunk:
    chunk_id: str
    path: str
    char_start: int
    char_end: int
    text: str
    source: str = ""
    ts: str | None = None
    people: list[str] = field(default_factory=list)
    label: str = ""  # human-readable source name shown to the user, e.g. "Priya Sharma (dossier)"
    sender: str = ""  # the sender's address, lower case (email excerpts only)


def is_signature(source: str, chunk_id: str) -> bool:
    """An email signature chunk (`s{i}`, connectors/gmail.py): the same text recurs in every
    message someone signs, so search and evidence keep one per sender and text."""
    return source == "gmail" and chunk_id.startswith("s")


def signature_key(source: str, chunk_id: str, sender: str, text: str) -> tuple[str, str] | None:
    return (sender.lower(), " ".join(text.split()).lower()) if is_signature(source, chunk_id) else None


RawChunker = Callable[[str, dict], list[Chunk]]
_RAW: dict[str, RawChunker] = {}


def register_raw_chunker(source: str, fn: RawChunker) -> None:
    _RAW[source] = fn


def _windows(text: str, base: int, max_words: int, overlap: int) -> list[tuple[int, int]]:
    words = [m.span() for m in re.finditer(r"\S+", text)]
    if not words:
        return []
    if len(words) <= max_words:
        return [(base + words[0][0], base + words[-1][1])]
    spans, step, i = [], max_words - overlap, 0
    while True:
        last = min(i + max_words, len(words)) - 1
        spans.append((base + words[i][0], base + words[last][1]))
        if last == len(words) - 1:
            return spans
        i += step


def chunk_windows(path: str, text: str, base: int = 0, max_words: int = MAX_WORDS,
                  overlap_words: int = OVERLAP_WORDS, source: str = "", ts: str | None = None) -> list[Chunk]:
    return [Chunk(f"c{n}", path, s, e, text[s - base : e - base], source=source, ts=ts)
            for n, (s, e) in enumerate(_windows(text, base, max_words, overlap_words))]


_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)


def chunk_markdown(path: str, text: str, max_words: int = MAX_WORDS, overlap_words: int = OVERLAP_WORDS,
                   source: str = "", ts: str | None = None) -> list[Chunk]:
    cuts = [0]
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            cuts.append(end + 5)
    body_start = cuts[-1]
    cuts += [m.start() for m in _HEADING.finditer(text, body_start) if m.start() > body_start]
    cuts.append(len(text))
    spans: list[tuple[int, int]] = []
    for a, b in zip(cuts, cuts[1:]):
        spans += _windows(text[a:b], a, max_words, overlap_words)
    return [Chunk(f"c{n}", path, s, e, text[s:e], source=source, ts=ts) for n, (s, e) in enumerate(spans)]


def _md_ts(text: str) -> str | None:
    m = re.search(r"^(?:start|created_at|date):\s*['\"]?([0-9T:\-+Z.]+)", text, re.MULTILINE)
    return m.group(1) if m else None


KINDS = {"people": "dossier", "meetings": "meeting notes", "loops": "open item", "briefings": "briefing",
         "projects": "project", "journal": "journal"}


def short_date(ts: str | None) -> str:
    from datetime import datetime

    try:
        d = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    d = d.astimezone() if d.tzinfo else d
    return f"{d:%b} {d.day}"


def _md_label(path: str, text: str, ts: str | None) -> str:
    m = re.search(r"^(?:title|name|summary):\s*['\"]?(.+?)['\"]?\s*$", text[:2000], re.MULTILINE)
    name = m.group(1) if m and text.startswith("---\n") else PurePosixPath(path).stem.replace("_", " ").replace("-", " ")
    kind = KINDS.get(PurePosixPath(path).parts[0], "")
    when = short_date(ts)
    detail = ", ".join(filter(None, [kind, when]))
    return f"{name} ({detail})" if detail else name


def chunk_file(path: str, text: str) -> list[Chunk]:
    """Chunk a file given its path relative to the Archie home."""
    parts = PurePosixPath(path).parts
    if path.endswith(".md"):
        ts = _md_ts(text)
        chunks = chunk_markdown(path, text, source=parts[0] if len(parts) > 1 else "", ts=ts)
        label = _md_label(path, text, ts)
        for c in chunks:
            c.label = label
        return chunks
    if path.endswith(".json") and len(parts) > 2 and parts[0] == "sources":
        import archie.connectors.registry  # noqa: F401  (registers connector chunkers)

        data = json.loads(text)
        fn = _RAW.get(parts[1])
        if fn is None or data.get("deleted"):
            return []
        return fn(path, data)
    return []

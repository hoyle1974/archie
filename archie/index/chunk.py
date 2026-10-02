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

CHUNKER_VERSION = "1"
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


def chunk_file(path: str, text: str) -> list[Chunk]:
    """Chunk a file given its path relative to the Archie home."""
    parts = PurePosixPath(path).parts
    if path.endswith(".md"):
        return chunk_markdown(path, text, source=parts[0] if len(parts) > 1 else "", ts=_md_ts(text))
    if path.endswith(".json") and len(parts) > 2 and parts[0] == "sources":
        data = json.loads(text)
        fn = _RAW.get(parts[1])
        if fn is None or data.get("deleted"):
            return []
        return fn(path, data)
    return []

"""Context packets and the citation verifier (DESIGN §2.5, §8).

The LLM only sees a numbered packet of source excerpts. It cites by number ("ref") plus a
verbatim quote. Code checks each quote against the excerpt it names; a claim with no
surviving citation is dropped and never shown. Refs, not file paths, are what the model
writes, so it cannot invent a source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_QUOTE_CHARS = 8

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", " ": " "})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().lower()


@dataclass
class PacketItem:
    ref: int
    path: str
    chunk_id: str
    text: str
    label: str = ""
    ts: str | None = None


@dataclass
class Packet:
    items: list[PacketItem] = field(default_factory=list)

    def add(self, path: str, chunk_id: str, text: str, label: str = "", ts: str | None = None) -> int:
        for it in self.items:
            if it.path == path and it.chunk_id == chunk_id:
                return it.ref
        ref = len(self.items) + 1
        self.items.append(PacketItem(ref, path, chunk_id, text, label or path, ts))
        return ref

    def get(self, ref: int) -> PacketItem | None:
        return self.items[ref - 1] if 1 <= ref <= len(self.items) else None

    def render(self) -> str:
        blocks = []
        for it in self.items:
            when = f" ({it.ts})" if it.ts else ""
            blocks.append(f"[{it.ref}] {it.label}{when}\n{it.text.strip()}")
        return "\n\n".join(blocks)


@dataclass
class Citation:
    ref: int
    path: str
    chunk_id: str
    quote: str
    label: str = ""


@dataclass
class Claim:
    text: str
    citations: list[Citation]
    extra: dict = field(default_factory=dict)


@dataclass
class Verified:
    kept: list[Claim] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)


def check_quote(packet: Packet, ref: int, quote: str) -> Citation | None:
    item = packet.get(ref)
    q = normalize(quote or "")
    if item is None or len(q) < MIN_QUOTE_CHARS or q not in normalize(item.text):
        return None
    return Citation(ref, item.path, item.chunk_id, quote, item.label)


def verify_claims(claims: list[dict], packet: Packet) -> Verified:
    out = Verified()
    for raw in claims:
        good = [c for c in (check_quote(packet, int(cit.get("ref", 0)), cit.get("quote", ""))
                            for cit in raw.get("citations") or []) if c]
        if good:
            extra = {k: v for k, v in raw.items() if k not in ("text", "citations")}
            out.kept.append(Claim(raw.get("text", ""), good, extra))
        else:
            out.dropped.append(raw)
    return out

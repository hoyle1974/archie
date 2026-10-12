"""Context packets and the citation verifier (DESIGN §2.5, §8).

The LLM only sees a numbered packet of source excerpts. It cites by number ("ref") plus a
verbatim quote. Code checks each quote against the excerpt it names; a claim with no
surviving citation never reaches `kept` (never shown as fact), but isn't thrown away: it
lands in `dropped` as an `Unverified`, which the caller may still show, clearly labeled, so
the user decides whether to trust it. Refs, not file paths, are what the model writes, so it
cannot invent a source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_QUOTE_CHARS = 8
# Quotes that are verbatim but can't show anything: "Workperson Acorn <workperson@x.io>", "Hi Ms. Workpersonfour & Maestra,",
# "Re: Student Support Team Meeting". The claim they were attached to is dropped.
_HOLLOW = re.compile(
    r"^(?:[\w .,'’&-]*<[^<>@\s]+@[^<>\s]+>[\s,;]*)+$"  # names and addresses only
    r"|^(?:hi|hello|hey|dear|good (?:morning|afternoon|evening))\b.{0,40}[,!:]$"  # a greeting line
    r"|^(?:re|fwd?|subject):\s",  # a subject line
    re.IGNORECASE)

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", " ": " "})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().lower()


_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)  # fences and hidden citation blocks in derived notes
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE = re.compile(r"\[image:[^\]]*\]", re.IGNORECASE)
_LONG_URL = re.compile(r"<?https?://\S{50,}>?")
_FOOTER = re.compile(r"unsubscribe|you received this (?:email|message)|view (?:it )?in (?:your )?browser|"
                     r"manage (?:your )?(?:preferences|subscription)|email preferences", re.IGNORECASE)
_HEADER_TIME = re.compile(r"^(From .*?), (\d{4}-\d\d-\d\dT\d\d:\d\d)$", re.MULTILINE)


def tidy(text: str) -> str:
    """What the model reads: the excerpt without data blocks, tracking links, images,
    unsubscribe footers and UTC header times. Quotes are still checked against the original,
    so tidying can never let an unverifiable claim through."""
    from archie.store.times import when

    text = _FRONTMATTER.sub("", text)
    text = _COMMENT.sub("", text)
    text = _HEADER_TIME.sub(lambda m: f"{m.group(1)}, {when(m.group(2) + '+00:00')}", text)
    text = _MD_IMAGE.sub("", _IMAGE.sub("(image)", text))
    text = _LONG_URL.sub("<link>", text)
    lines = [ln.rstrip() for ln in text.splitlines()
             if not _FOOTER.search(ln) and ln.strip() not in ("|", "￼", "<link>")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


@dataclass
class PacketItem:
    ref: int
    path: str
    chunk_id: str
    text: str
    label: str = ""
    ts: str | None = None
    score: float | None = None  # search match, 0–1 relative to the best source
    note: str = ""  # computed by code and shown after the excerpt (e.g. other dates of a repeating event)


@dataclass
class Packet:
    items: list[PacketItem] = field(default_factory=list)

    def add(self, path: str, chunk_id: str, text: str, label: str = "", ts: str | None = None,
            score: float | None = None, note: str = "") -> int:
        for it in self.items:
            if it.path == path and it.chunk_id == chunk_id:
                return it.ref
        ref = len(self.items) + 1
        self.items.append(PacketItem(ref, path, chunk_id, text, label or path, ts, score, note))
        return ref

    def get(self, ref: int) -> PacketItem | None:
        return self.items[ref - 1] if 1 <= ref <= len(self.items) else None

    def render(self) -> str:
        """Each excerpt in a <source> block (emails contain brackets, so plain `[n]` lines alone
        are ambiguous): its match score, then `[n] label` (the label names the source and its
        local date) and the tidied text."""
        blocks = []
        for it in self.items:
            match = f' match="{it.score:.2f}"' if it.score is not None else ""
            body = tidy(it.text)
            if not body and not it.note:
                continue  # only a data block (e.g. an empty notes file): nothing to read
            note = f"\n{it.note}" if it.note else ""
            blocks.append(f'<source n="{it.ref}"{match}>\n[{it.ref}] {it.label}\n{body}{note}\n</source>')
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
class Unverified:
    """A claim with no citation that survived verification. `near` lists the label of any
    cited ref that pointed at a real source chunk even though its quote failed to match
    (an empty list means the model gave no usable citation at all)."""
    text: str
    near: list[str] = field(default_factory=list)


@dataclass
class Verified:
    kept: list[Claim] = field(default_factory=list)
    dropped: list[Unverified] = field(default_factory=list)


def check_quote(packet: Packet, ref: int, quote: str) -> Citation | None:
    item = packet.get(ref)
    q = normalize(quote or "")
    if item is None or len(q) < MIN_QUOTE_CHARS or q not in normalize(item.text) or _HOLLOW.match(q.strip()):
        return None
    return Citation(ref, item.path, item.chunk_id, quote, item.label)


def verify_claims(claims: list[dict], packet: Packet) -> Verified:
    out = Verified()
    for raw in claims:
        cits = raw.get("citations") or []
        good = [c for c in (check_quote(packet, int(cit.get("ref", 0)), cit.get("quote", "")) for cit in cits) if c]
        if good:
            extra = {k: v for k, v in raw.items() if k not in ("text", "citations")}
            out.kept.append(Claim(raw.get("text", ""), good, extra))
        else:
            near, seen = [], set()
            for cit in cits:
                item = packet.get(int(cit.get("ref", 0) or 0))
                if item and item.label not in seen:
                    seen.add(item.label)
                    near.append(item.label)
            out.dropped.append(Unverified(raw.get("text", ""), near))
    return out

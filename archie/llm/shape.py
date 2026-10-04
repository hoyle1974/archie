"""Line-format model replies (DESIGN §9). Each model call declares a `Shape`; from it, code
writes the format instructions, parses the reply into the dict the caller uses, and checks
it. No JSON and no schema is sent to the model.

- Fields are `key: value` lines; `-` is empty; `;` separates list items; yes/no for flags.
- Repeated records start with an UPPERCASE keyword line, e.g. `LOOP asked_of_me`.
- A citation is `[n] "words copied exactly from source n"`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NULLS = {"", "-", "none", "null", "n/a"}
OPEN_QUOTES, CLOSE_QUOTES = "\"“'‘", "\"”'’"
KIND_TEXT = {"text": "text", "quote": "words copied exactly", "list": "list, separated by ;", "int": "a number",
             "int_list": "numbers, separated by ;", "bool": "yes or no",
             "cite": '[n] "words copied exactly from source n"'}
_BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_HEADING = re.compile(r"^#{1,6}\s")
_HEAD = re.compile(r"^([A-Za-z_]+)\b[:\s]*(.*)$")
_KV = re.compile(r"^([A-Za-z][\w ]*?)\s*:\s*(.*)$")
_CITE = re.compile(r"\[(\d+)\]\s*(?=[\"“'‘])")
_MARK = re.compile(r"\[(\d+)\]")
_SUMMARY = re.compile(r"^#*\s*summary\s*:?$", re.I)
CLAIMS_FORMAT = (
    "Reply in this plain format, not JSON:\n"
    "SUMMARY\n"
    "<1 to 4 short sentences, one per line, each ending with its citations>\n"
    "## <Heading>\n"
    "- <one short fact, ending with its citations>\n"
    'A citation is [n] "words copied exactly from source n" (8+ characters). A line may end with '
    "several citations. Put citations at the end of the line, never in the middle. Write SUMMARY "
    "with nothing under it if the sources don't answer the question.\n"
    "Example:\n"
    "SUMMARY\n"
    'Your replacement earbud was delivered Oct 2. [1] "Your order\'s arrived"\n'
    "## How it unfolded\n"
    '- Status offered a right earbud for $49. [3] "replacement right earbud for $49"'
)


@dataclass(frozen=True)
class F:
    """One field. `keys` is where a cite's number and quote land in the parsed dict."""

    name: str
    kind: str = "text"
    required: bool = True
    choices: tuple[str, ...] = ()
    keys: tuple[str, str] = ("ref", "quote")
    hint: str = ""
    lenient: bool = False  # a choice not on the list becomes empty instead of a problem

    def describe(self) -> str:
        what = f"one of {', '.join(self.choices)}" if self.kind == "choice" else KIND_TEXT[self.kind]
        if self.hint:
            what += f" ({self.hint})"
        return what if self.required else f"{what}, or -"


@dataclass(frozen=True)
class Record:
    keyword: str
    key: str
    head: F
    fields: tuple[F, ...] = ()


@dataclass(frozen=True)
class Shape:
    name: str
    fields: tuple[F, ...] = ()
    records: tuple[Record, ...] = ()
    nest: tuple[str, tuple[str, ...]] | None = None
    example: str = ""
    claims: bool = False

    def instructions(self) -> str:
        if self.claims:
            return CLAIMS_FORMAT
        out = ["Reply in this plain line format, not JSON: one `key: value` per line, `-` for an empty "
               "value, `;` between list items."]
        out += [f"{f.name}: {f.describe()}" for f in self.fields]
        for r in self.records:
            out.append("Then one block per item, starting with its keyword line (write NONE if there are none):")
            out.append(f"{r.keyword} <{r.head.name}: {r.head.describe()}>")
            out += [f"{f.name}: {f.describe()}" for f in r.fields]
        if self.example:
            out.append("Example:\n" + self.example)
        return "\n".join(out)

    def parse(self, text: str) -> tuple[dict, list[str]]:
        return (_parse_claims(text), []) if self.claims else _parse_fields(self, text)


def _lines(text: str):
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("```"):
            yield line


def _unquote(text: str) -> str:
    text = text.strip().rstrip(".,;").strip()
    if text[:1] in OPEN_QUOTES:
        text = text[1:]
    if text[-1:] in CLOSE_QUOTES:
        text = text[:-1]
    return text.strip()


def _unwrap(text: str) -> str:
    """Drop quote marks around the whole value, keeping everything else as written."""
    inner = text.rstrip(".,;").strip()
    if len(inner) >= 2 and inner[0] in OPEN_QUOTES and inner[-1] in CLOSE_QUOTES:
        return inner[1:-1].strip()
    return text


def _put(out: dict, f: F, raw: str | None, problems: list[str], where: str) -> None:
    value = None if raw is None or raw.strip().lower() in NULLS else raw.strip()
    if value is None:
        if f.required:
            problems.append(f"missing `{where}{f.name}`")
        if f.kind != "cite":
            out[f.name] = {"list": [], "int_list": [], "bool": False}.get(f.kind)
        return
    try:
        if f.kind == "text":
            out[f.name] = value
        elif f.kind == "quote":
            out[f.name] = _unwrap(value)
        elif f.kind == "list":
            items = value.split(";" if ";" in value else ",")
            out[f.name] = [x.strip() for x in items if x.strip().lower() not in NULLS]
        elif f.kind == "int":
            out[f.name] = int(re.match(r"\[?(-?\d+)", value).group(1))
        elif f.kind == "int_list":
            heads = (re.match(r"\s*\[?(\d+)", x) for x in re.split(r"[;,]", value))
            out[f.name] = [int(m.group(1)) for m in heads if m]
        elif f.kind == "bool":
            flag = {"yes": True, "y": True, "true": True, "no": False, "n": False, "false": False}[value.lower()]
            out[f.name] = flag
        elif f.kind == "choice":
            norm = re.sub(r"[\s-]+", "_", value.lower())
            if norm not in f.choices and not f.lenient:
                raise ValueError(norm)
            out[f.name] = norm if norm in f.choices else None
        elif f.kind == "cite":
            m = re.match(r"\[?(\d+)\]?\s*(.*)$", value)
            out[f.keys[0]], out[f.keys[1]] = int(m.group(1)), _unquote(m.group(2))
    except (AttributeError, KeyError, ValueError):
        problems.append(f"`{where}{f.name}` should be {f.describe()}, not {value!r}")


def _parse_fields(shape: Shape, text: str) -> tuple[dict, list[str]]:
    top = {f.name for f in shape.fields}
    recs = {r.keyword: r for r in shape.records}
    raw_top: dict[str, str] = {}
    blocks: list[tuple[Record, dict[str, str]]] = []
    said_none = False
    for line in _lines(text):
        line = _BULLET.sub("", line.replace("**", "")).strip()
        if line.upper() == "NONE":
            said_none = True
            continue
        head = _HEAD.match(line)
        if head and head.group(1).upper() in recs and (
                head.group(1).isupper() or re.fullmatch(r"[A-Za-z_]*", head.group(2).strip())):
            blocks.append((recs[head.group(1).upper()], {"": head.group(2)}))
            continue
        kv = _KV.match(line)
        if not kv:
            continue
        key, value = kv.group(1).strip().lower().replace(" ", "_"), kv.group(2)
        if blocks and key in {f.name for f in blocks[-1][0].fields}:
            blocks[-1][1].setdefault(key, value)  # a later look-alike line (pasted text) can't override
        elif blocks and key == blocks[-1][0].head.name and not blocks[-1][1][""].strip():
            blocks[-1][1][""] = value
        elif key in top:
            raw_top.setdefault(key, value)  # a later look-alike line (e.g. inside pasted text) can't override
    problems: list[str] = []
    if shape.records and not shape.fields and not blocks and not said_none:
        problems.append(f"no {'/'.join(r.keyword for r in shape.records)} blocks and no NONE")
    out: dict = {}
    for f in shape.fields:
        _put(out, f, raw_top.get(f.name), problems, "")
    for r in shape.records:
        out[r.key] = []
    for r, raw in blocks:
        item: dict = {}
        _put(item, r.head, raw.get(""), problems, f"{r.keyword} ")
        for f in r.fields:
            _put(item, f, raw.get(f.name), problems, f"{r.keyword} ")
        out[r.key].append(item)
    if shape.nest:
        key, names = shape.nest
        out[key] = {n: out.pop(n) for n in names}
    return out, problems


def _claim_text(text: str) -> str:
    text = re.sub(r"\s+", " ", _MARK.sub("", text)).strip()
    return re.sub(r"\s+([.,;:])", r"\1", text)


def _claim(line: str) -> dict:
    cites = list(_CITE.finditer(line))
    if not cites:
        return {"text": _claim_text(line),
                "citations": [{"ref": int(m.group(1)), "quote": ""} for m in _MARK.finditer(line)]}
    out = []
    for i, m in enumerate(cites):
        end = cites[i + 1].start() if i + 1 < len(cites) else len(line)
        out.append({"ref": int(m.group(1)), "quote": _unquote(line[m.end():end])})
    return {"text": _claim_text(line[:cites[0].start()]), "citations": out}


def _parse_claims(text: str) -> dict:
    lines = list(_lines(text))
    started = not any(_SUMMARY.match(x) for x in lines)
    summary: list[dict] = []
    sections: list[dict] = []
    current: dict | None = None
    for line in lines:
        if _SUMMARY.match(line):
            started, current = True, None
        elif not started:
            continue
        elif _HEADING.match(line):
            current = {"heading": line.lstrip("#").strip(), "items": []}
            sections.append(current)
        else:
            claim = _claim(_BULLET.sub("", line))
            if claim["text"] or claim["citations"]:
                (current["items"] if current else summary).append(claim)
    return {"summary": summary, "sections": [s for s in sections if s["items"]]}

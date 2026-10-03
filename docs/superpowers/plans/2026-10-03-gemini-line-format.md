# Gemini Backend with a Line Output Format: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `claude -p` backend and JSON-schema output with the Gemini API and a plain line format that code parses and checks.

**Architecture:** A new `archie/llm/shape.py` defines `Shape` (fields, records, or cited claims). Each of the 13 model call sites declares one of 11 shapes instead of a JSON schema. `TextBackend.complete(system, user, shape, tier)` appends the shape's format instructions, calls `generate()` (text in, text out), parses into the same dict the caller uses today, checks it, and retries once. `GeminiBackend` implements `generate()` with the `google-genai` SDK. Claude is removed.

**Tech Stack:** Python 3.12, `google-genai` (2.28+), pytest, uv, keyring (existing `archie/secrets.py`).

**Spec:** `docs/superpowers/specs/2026-10-03-gemini-line-format-design.md`

## Global Constraints

- DESIGN §2.5: the model cites `[n] "quote"`; `archie/llm/verify.py` is unchanged and still drops unverified claims. Counts and dates come from code.
- No tools, no function calling, no file access in model calls.
- The Gemini key lives only in the Keychain item `gemini-api-key` (service `archie`), read through `archie.secrets.get_secret`. Never in `~/.archie/` or the repo.
- Handlers keep receiving the same dict keys they read today.
- Defaults: `models: {fast: gemini-3.7-flash, strong: gemini-3.1-pro-preview}`, `max_output_tokens: {fast: 2048, strong: 8192}`, `thinking: {fast: low, strong: medium}`, timeouts 60 s fast and 300 s strong.
- User-facing errors are one plain-English sentence; no stack traces, no IDs leading.
- Code comments only state constraints the code can't show; match the surrounding density.
- Before every commit: update the OKF bundle where the task says so; the pre-commit hook runs `scripts/okf_check.py`. Don't bypass it.
- Baseline before starting: `uv run pytest -q` → 285 passed, 4 xfailed.

## Review Focus

1. The model wraps its reply in a code fence, adds a preamble, bolds keys or capitalizes them (`**Intent:** search`): it must still parse. Test: Task 1 `test_forgiving_about_fences_chatter_bullets_bold_and_key_case`.
2. An answer quote contains a `"` or curly quotes, or a claim puts `[n]` mid-sentence: the quote must reach the verifier intact and the claim text must stay readable. Tests: Task 2 `test_quote_may_contain_double_quotes_and_bare_markers_get_empty_quotes`, `test_claims_summary_sections_and_several_citations`.
3. Gemini returns no text (safety block, or the output cap hit during thinking): a plain `LLMError`, not a crash in a deriver. Test: Task 5 `test_empty_reply_is_explained`.
4. Several derivers call the model in parallel threads on first use, or the Keychain dialog is pending: the client is created once, and the Keychain wait surfaces as an `LLMError` (derivers already catch `LLMError`). Tests: Task 5 `test_client_is_created_once_across_threads`, `test_keychain_wait_becomes_llm_error`.
5. A reply that still fails after the retry: one plain `LLMError` naming the problem, and `ask` prints it through the existing "couldn't reach its language model" path. Test: Task 4 `test_text_backend_retries_once_then_explains`.

---

## Before Task 1

The working tree has the user's uncommitted sync-progress changes (`archie/cli.py`, `archie/sync.py`, `archie/tui/app.py`, `okf/log.md`, …). Tasks 5 and 6 edit `archie/cli.py` and `okf/log.md`. Confirm with the user that those changes are committed (or committed by you at their request) before starting, so every task's commit contains only its own work.

```bash
git status --short   # expect clean
uv run pytest -q     # expect 285 passed, 4 xfailed
```

---

### Task 1: `Shape` with fields and records

**Files:**
- Create: `archie/llm/shape.py`
- Test: `tests/unit/test_shape.py`

**Interfaces:**
- Produces: `F(name, kind="text", required=True, choices=(), keys=("ref","quote"), hint="")`, kinds `text|list|int|int_list|bool|choice|cite`; `Record(keyword, key, head: F, fields: tuple[F,...]=())`; `Shape(name, fields=(), records=(), nest=None, example="", claims=False)` with `instructions() -> str` and `parse(text) -> tuple[dict, list[str]]`. Optional fields that are absent or `-` parse to `None` (text/int/choice), `[]` (list/int_list), `False` (bool), or no keys at all (cite).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_shape.py`:

```python
from archie.llm.shape import F, Record, Shape

ROUTE = Shape(
    "route",
    fields=(F("intent", "choice", choices=("search", "remember", "loop_update")),
            F("people", "list", required=False), F("since", required=False), F("text", required=False)),
    records=(Record("ALSO", "also", F("intent", "choice", choices=("remember", "loop_update")), (F("text"),)),),
    nest=("params", ("people", "since", "text")),
    example="intent: search\npeople: -\nsince: -\ntext: -",
)
LOOPS = Shape("loops_extract", records=(Record("LOOP", "loops", F("kind", "choice", choices=("asked_of_me", "waiting_on")), (
    F("summary"), F("cite", "cite", keys=("ref", "quote")), F("resolved", "bool", required=False),
    F("resolved_cite", "cite", required=False, keys=("resolved_ref", "resolved_quote")))),))


def test_fields_lists_nulls_and_nesting():
    out, problems = ROUTE.parse("intent: search\npeople: Alex Rivera; priya@x.example\nsince: -\ntext: none")
    assert problems == []
    assert out == {"intent": "search", "also": [],
                   "params": {"people": ["Alex Rivera", "priya@x.example"], "since": None, "text": None}}


def test_forgiving_about_fences_chatter_bullets_bold_and_key_case():
    reply = "Sure! Here you go:\n```\n- **Intent:** remember\n* People: Goodspouse\n```\nHope that helps."
    out, problems = ROUTE.parse(reply)
    assert problems == []
    assert out["intent"] == "remember" and out["params"]["people"] == ["Goodspouse"]


def test_records_with_head_cites_and_optional_fields():
    reply = ('LOOP asked_of_me\nsummary: Review the patch\ncite: [3] "can you review the patch before Friday"\n'
             'resolved: no\nresolved_cite: -\n\nLOOP: waiting on\nsummary: Get SSO dates\n'
             'cite: [5] “when is SSO launching?”\nresolved: yes\nresolved_cite: [6] "SSO launches Oct 20"')
    out, problems = LOOPS.parse(reply)
    assert problems == []
    assert out["loops"][0] == {"kind": "asked_of_me", "summary": "Review the patch", "ref": 3,
                               "quote": "can you review the patch before Friday", "resolved": False}
    second = out["loops"][1]
    assert second["kind"] == "waiting_on" and second["quote"] == "when is SSO launching?"
    assert (second["resolved_ref"], second["resolved_quote"]) == (6, "SSO launches Oct 20")


def test_none_means_no_records():
    assert LOOPS.parse("NONE") == ({"loops": []}, [])


def test_records_come_after_top_level_fields():
    out, problems = ROUTE.parse("intent: loop_update\ntext: -\nALSO remember\ntext: Sam is my neighbor.")
    assert problems == []
    assert out["also"] == [{"intent": "remember", "text": "Sam is my neighbor."}]
    assert out["params"]["text"] is None


def test_problems_name_the_field():
    assert ROUTE.parse("people: Alex")[1] == ["missing `intent`"]
    assert "`intent` should be one of search, remember, loop_update" in ROUTE.parse("intent: dance")[1][0]
    problems = LOOPS.parse("LOOP asked_of_me\nsummary: x\ncite: [x] nope\nresolved: maybe")[1]
    assert any("`LOOP cite`" in p for p in problems) and any("`LOOP resolved`" in p for p in problems)


def test_instructions_list_fields_records_and_example():
    text = LOOPS.instructions()
    assert "not JSON" in text and "LOOP <kind: one of asked_of_me, waiting_on>" in text
    assert 'cite: [n] "words copied exactly from source n"' in text and "NONE" in text
    assert "intent: one of search, remember, loop_update" in ROUTE.instructions()
    assert "people: list, separated by ;, or -" in ROUTE.instructions()
    assert ROUTE.instructions().endswith("Example:\nintent: search\npeople: -\nsince: -\ntext: -")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_shape.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'archie.llm.shape'`

- [ ] **Step 3: Implement `archie/llm/shape.py`**

```python
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
KIND_TEXT = {"text": "text", "list": "list, separated by ;", "int": "a number",
             "int_list": "numbers, separated by ;", "bool": "yes or no",
             "cite": '[n] "words copied exactly from source n"'}
_BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_HEAD = re.compile(r"^([A-Za-z_]+)\b[:\s]*(.*)$")
_KV = re.compile(r"^([A-Za-z][\w ]*?)\s*:\s*(.*)$")


@dataclass(frozen=True)
class F:
    """One field. `keys` is where a cite's number and quote land in the parsed dict."""

    name: str
    kind: str = "text"
    required: bool = True
    choices: tuple[str, ...] = ()
    keys: tuple[str, str] = ("ref", "quote")
    hint: str = ""

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
        return _parse_fields(self, text)


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
        elif f.kind == "list":
            out[f.name] = [x.strip() for x in value.split(";") if x.strip().lower() not in NULLS]
        elif f.kind == "int":
            out[f.name] = int(re.match(r"\[?(-?\d+)", value).group(1))
        elif f.kind == "int_list":
            out[f.name] = [int(x) for x in re.findall(r"\d+", value)]
        elif f.kind == "bool":
            flag = {"yes": True, "y": True, "true": True, "no": False, "n": False, "false": False}[value.lower()]
            out[f.name] = flag
        elif f.kind == "choice":
            norm = re.sub(r"[\s-]+", "_", value.lower())
            if norm not in f.choices:
                raise ValueError(norm)
            out[f.name] = norm
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
    for line in _lines(text):
        line = _BULLET.sub("", line.replace("**", "")).strip()
        head = _HEAD.match(line)
        if head and head.group(1).upper() in recs:
            blocks.append((recs[head.group(1).upper()], {"": head.group(2)}))
            continue
        kv = _KV.match(line)
        if not kv:
            continue
        key, value = kv.group(1).strip().lower().replace(" ", "_"), kv.group(2)
        if blocks and key in {f.name for f in blocks[-1][0].fields}:
            blocks[-1][1][key] = value
        elif blocks and key == blocks[-1][0].head.name:
            blocks[-1][1][""] = value
        elif key in top:
            raw_top[key] = value
    problems: list[str] = []
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_shape.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

`archie/llm/` is already covered by `okf/components/llm.md` (resource `archie/llm/`); the OKF text is updated in Task 6.

```bash
git add archie/llm/shape.py tests/unit/test_shape.py
git commit -m "Add Shape: line-format replies with fields and records"
```

---

### Task 2: Cited-claims shape for answers

**Files:**
- Modify: `archie/llm/shape.py`
- Test: `tests/unit/test_shape.py`

**Interfaces:**
- Consumes: `Shape`, `_lines`, `_unquote`, `_BULLET` from Task 1.
- Produces: `Shape(name, claims=True)` whose `parse()` returns `({"summary": [claim...], "sections": [{"heading": str, "items": [claim...]}]}, [])` where a claim is `{"text": str, "citations": [{"ref": int, "quote": str}]}` (the input `verify_claims` already takes). Sections with no items are dropped. Claims parsing never reports problems: an empty summary means "not found".

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_shape.py`)

```python
ANSWER = Shape("answer", claims=True)


def test_claims_summary_sections_and_several_citations():
    reply = ('Here is what I found.\nSUMMARY\nYour earbud was delivered Oct 2. [1] "Your order\'s arrived"\n'
             '## How it unfolded\n- It shipped Sep 29. [5] “has shipped” [4] "Order #507509S"\n## Empty\n')
    out, problems = ANSWER.parse(reply)
    assert problems == []
    assert out["summary"] == [{"text": "Your earbud was delivered Oct 2.",
                               "citations": [{"ref": 1, "quote": "Your order's arrived"}]}]
    assert out["sections"] == [{"heading": "How it unfolded", "items": [
        {"text": "It shipped Sep 29.", "citations": [{"ref": 5, "quote": "has shipped"},
                                                     {"ref": 4, "quote": "Order #507509S"}]}]}]


def test_quote_may_contain_double_quotes_and_bare_markers_get_empty_quotes():
    out, _ = ANSWER.parse('SUMMARY\nShe wrote back. [2] "the subject was "Yeti bundle" today"\nAlex merged it [3].')
    assert out["summary"][0]["citations"] == [{"ref": 2, "quote": 'the subject was "Yeti bundle" today'}]
    assert out["summary"][1] == {"text": "Alex merged it.", "citations": [{"ref": 3, "quote": ""}]}


def test_empty_summary_means_not_found_and_no_marker_reads_from_the_top():
    assert ANSWER.parse("SUMMARY\n") == ({"summary": [], "sections": []}, [])
    out, _ = ANSWER.parse('```\nDelivered Oct 2. [1] "Your order\'s arrived"\n```')
    assert out["summary"][0]["citations"] == [{"ref": 1, "quote": "Your order's arrived"}]


def test_claims_instructions():
    text = ANSWER.instructions()
    assert "SUMMARY" in text and "## <Heading>" in text and '[n] "words copied exactly from source n"' in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_shape.py -q`
Expected: the 4 new tests FAIL (`ANSWER.parse` goes through the fields parser and returns `{}`).

- [ ] **Step 3: Implement**

In `archie/llm/shape.py`, add after the `_KV` line:

```python
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
```

Replace the bodies of `Shape.instructions` and `Shape.parse` so they start with the claims branch:

```python
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
```

Add at the end of the module:

```python
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
        elif line.startswith("#"):
            current = {"heading": line.lstrip("#").strip(), "items": []}
            sections.append(current)
        else:
            claim = _claim(_BULLET.sub("", line))
            if claim["text"] or claim["citations"]:
                (current["items"] if current else summary).append(claim)
    return {"summary": summary, "sections": [s for s in sections if s["items"]]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_shape.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add archie/llm/shape.py tests/unit/test_shape.py
git commit -m "Shape: cited claims for answers"
```

---

### Task 3: Declare the 11 shapes at their call sites

Shapes are added next to the existing `SCHEMA` constants. Nothing uses them yet; Task 4 switches over.

**Files:**
- Modify: `archie/ask/router.py`, `archie/ask/synthesize.py`, `archie/ask/intents/clarify.py`, `archie/ask/intents/correct.py`, `archie/ask/intents/loops.py`, `archie/ask/intents/notes.py`, `archie/ask/intents/remember.py`, `archie/derive/loops.py`, `archie/derive/cross_close.py`, `archie/derive/enrich.py`
- Test: `tests/unit/test_shapes.py`

**Interfaces:**
- Consumes: `F`, `Record`, `Shape` from `archie.llm.shape`.
- Produces: `router.SHAPE` ("route"), `synthesize.SHAPE` ("answer"), `clarify.SHAPE`, `correct.SHAPE`, `intents.loops.UPDATE_SHAPE` ("loop_update"), `notes.SHAPE` ("notes_actions"), `remember.SHAPE`, `derive.loops.EXTRACT_SHAPE` ("loops_extract") and `CLOSE_SHAPE` ("loops_close"), `cross_close.SHAPE` ("loops_cross"), `enrich.SHAPE` ("people_facts").

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_shapes.py`:

```python
import pytest

from archie.ask.intents.clarify import SHAPE as CLARIFY
from archie.ask.intents.correct import SHAPE as CORRECT
from archie.ask.intents.loops import UPDATE_SHAPE as UPDATE
from archie.ask.intents.notes import SHAPE as NOTES
from archie.ask.intents.remember import SHAPE as REMEMBER
from archie.ask.router import SHAPE as ROUTE
from archie.ask.synthesize import SHAPE as ANSWER
from archie.derive.cross_close import SHAPE as CROSS
from archie.derive.enrich import SHAPE as FACTS
from archie.derive.loops import CLOSE_SHAPE as CLOSE
from archie.derive.loops import EXTRACT_SHAPE as EXTRACT

ALL = [ROUTE, ANSWER, CLARIFY, CORRECT, UPDATE, NOTES, REMEMBER, EXTRACT, CLOSE, CROSS, FACTS]


def test_eleven_shapes_named_like_the_old_schemas():
    assert sorted(s.name for s in ALL) == sorted(["route", "answer", "clarify", "correct", "loop_update",
                                                  "notes_actions", "remember", "loops_extract", "loops_close",
                                                  "loops_cross", "people_facts"])


@pytest.mark.parametrize("shape", [s for s in ALL if not s.claims], ids=lambda s: s.name)
def test_each_example_parses_cleanly(shape):
    out, problems = shape.parse(shape.example)
    assert problems == [] and out


def test_route():
    out, problems = ROUTE.parse("intent: loop_update\npeople: Ken\nsince: -\nuntil: -\ntopic: -\nmeeting: -\n"
                                "text: -\nALSO remember\ntext: Sam is my neighbor.")
    assert problems == []
    assert out == {"intent": "loop_update", "also": [{"intent": "remember", "text": "Sam is my neighbor."}],
                   "params": {"people": ["Ken"], "since": None, "until": None, "topic": None, "meeting": None,
                              "text": None}}


def test_clarify():
    assert CLARIFY.parse("ANSWER 2\nsame: yes\nANSWER 1\nsame: no") == (
        {"answers": [{"question": 2, "same": True}, {"question": 1, "same": False}]}, [])


def test_correct():
    out, problems = CORRECT.parse("kind: same_person\nalias: Al R.\nperson: Alex Rivera")
    assert problems == []
    assert out == {"kind": "same_person", "meeting": None, "meeting_type": None, "alias": "Al R.",
                   "person": "Alex Rivera", "role": None}


def test_loop_update():
    assert UPDATE.parse("action: snooze\nloops: 2; 3\nuntil: 2026-10-05\nreason: -") == (
        {"action": "snooze", "loops": [2, 3], "until": "2026-10-05", "reason": None}, [])
    assert UPDATE.parse("action: done\nloops: -")[0]["loops"] == []


def test_notes_actions():
    out, problems = NOTES.parse("ITEM me\ntext: Update the runbook\nquote: I need to update the runbook by next Wed\n"
                                "ITEM Alex\ntext: Add a circuit breaker\nquote: Alex to add circuit breaker")
    assert problems == []
    assert out["items"][0] == {"owner": "me", "text": "Update the runbook",
                               "quote": "I need to update the runbook by next Wed"}
    assert out["items"][1]["owner"] == "Alex"


def test_remember():
    out, problems = REMEMBER.parse("PERSON Goodspouse\nrelationship: wife\nrole: -\npronouns: she/her\nidentity: -\n"
                                   "avoid: -\nother_names: Belle; Goodspouse Mae Testerson\nstatement: Goodspouse is my wife.")
    assert problems == []
    assert out == {"people": [{"name": "Goodspouse", "relationship": "wife", "role": None, "pronouns": "she/her",
                               "identity": None, "avoid": [], "other_names": ["Belle", "Goodspouse Mae Testerson"],
                               "statement": "Goodspouse is my wife."}]}


def test_loops_extract_and_close():
    out, problems = EXTRACT.parse('LOOP asked_of_me\nsummary: Review the patch\n'
                                  'cite: [3] "can you review the patch before Friday"\nresolved: no')
    assert problems == []
    assert out["loops"] == [{"kind": "asked_of_me", "summary": "Review the patch", "ref": 3,
                             "quote": "can you review the patch before Friday", "resolved": False}]
    out, problems = CLOSE.parse('UPDATE 1\nresolved: yes\ncite: [4] "I merged the fix this morning"\n'
                                'UPDATE 2\nresolved: no\ncite: -')
    assert problems == []
    assert out["updates"] == [{"loop": 1, "resolved": True, "ref": 4, "quote": "I merged the fix this morning"},
                              {"loop": 2, "resolved": False}]


def test_loops_cross():
    assert CROSS.parse("done: no\nstrength: -\ncite: -") == ({"done": False, "strength": None}, [])
    out, _ = CROSS.parse('done: yes\nstrength: weak\ncite: [2] "Approved the fallback patch"')
    assert out == {"done": True, "strength": "weak", "ref": 2, "quote": "Approved the fallback patch"}


def test_people_facts():
    out, problems = FACTS.parse('FACT Product manager for auth\ncite: [2] "I\'m the PM for auth"\nNONE')
    assert problems == []
    assert out == {"facts": [{"text": "Product manager for auth", "ref": 2, "quote": "I'm the PM for auth"}]}


def test_answer_is_claims():
    assert ANSWER.claims and ANSWER.name == "answer"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_shapes.py -q`
Expected: FAIL with `ImportError: cannot import name 'SHAPE'`

- [ ] **Step 3: Add the shapes**

Add `from archie.llm.shape import F, Record, Shape` (only the names used) to each file's imports, then each shape directly below the file's existing `SCHEMA`.

`archie/ask/router.py` (imports `F, Record, Shape`; place after `SCHEMA`):

```python
_PARAMS = ("people", "since", "until", "topic", "meeting", "text")
SHAPE = Shape(
    "route",
    fields=(F("intent", "choice", choices=tuple(INTENT_HELP)),
            F("people", "list", required=False, hint="names or emails mentioned"),
            F("since", required=False, hint="ISO date"), F("until", required=False, hint="ISO date"),
            F("topic", required=False), F("meeting", required=False),
            F("text", required=False, hint="for notes: the note text verbatim")),
    records=(Record("ALSO", "also", F("intent", "choice", choices=tuple(INTENT_HELP)),
                    (F("text", hint="the exact sentences of that part"),)),),
    nest=("params", _PARAMS),
    example="intent: loop_update\npeople: Ken\nsince: -\nuntil: -\ntopic: -\nmeeting: -\ntext: -\n"
            "ALSO remember\ntext: Sam is my neighbor.",
)
```

`archie/ask/synthesize.py` (imports `Shape`):

```python
SHAPE = Shape("answer", claims=True)
```

`archie/ask/intents/clarify.py` (imports `F, Record, Shape`):

```python
SHAPE = Shape("clarify", records=(Record("ANSWER", "answers", F("question", "int", hint="question number"),
                                         (F("same", "bool", hint="yes = same person / finished / still needed"),)),),
              example="ANSWER 2\nsame: yes")
```

`archie/ask/intents/correct.py` (imports `F, Shape`):

```python
SHAPE = Shape("correct",
              fields=(F("kind", "choice", choices=("meeting_type", "same_person", "role")),
                      *(F(k, required=False) for k in ("meeting", "meeting_type", "alias", "person", "role"))),
              example="kind: same_person\nmeeting: -\nmeeting_type: -\nalias: Al R.\nperson: Alex Rivera\nrole: -")
```

`archie/ask/intents/loops.py` (imports `F, Shape`; after `UPDATE_SCHEMA`):

```python
UPDATE_SHAPE = Shape("loop_update",
                     fields=(F("action", "choice", choices=("done", "snooze", "dismiss", "reopen")),
                             F("loops", "int_list", required=False, hint="item numbers"),
                             F("until", required=False, hint="ISO date"), F("reason", required=False)),
                     example="action: snooze\nloops: 2; 3\nuntil: 2026-10-05\nreason: -")
```

`archie/ask/intents/notes.py` (imports `F, Record, Shape`):

```python
SHAPE = Shape("notes_actions",
              records=(Record("ITEM", "items", F("owner", hint="me, or the person's name as written"),
                              (F("text", hint="short imperative"),
                               F("quote", hint="words copied exactly from the notes"))),),
              example="ITEM me\ntext: Update the runbook\nquote: I need to update the runbook by next Wed")
```

`archie/ask/intents/remember.py` (imports `F, Record, Shape`):

```python
SHAPE = Shape("remember", records=(Record("PERSON", "people", F("name"), (
    F("relationship", required=False), F("role", required=False), F("pronouns", required=False),
    F("identity", required=False), F("avoid", "list", required=False), F("other_names", "list", required=False),
    F("statement", hint="their sentence(s) copied exactly from the message"))),),
    example="PERSON Goodspouse\nrelationship: wife\nrole: -\npronouns: she/her\nidentity: -\navoid: -\n"
            "other_names: Belle; Goodspouse Mae Testerson\nstatement: Goodspouse is my wife.")
```

`archie/derive/loops.py` (imports `F, Record, Shape`; after `CLOSE_SCHEMA`):

```python
EXTRACT_SHAPE = Shape("loops_extract", records=(Record("LOOP", "loops", F("kind", "choice", choices=KINDS), (
    F("summary", hint="short imperative"),
    F("cite", "cite", hint="the message number and words showing the request or promise"),
    F("resolved", "bool", required=False),
    F("resolved_cite", "cite", required=False, keys=("resolved_ref", "resolved_quote")))),),
    example='LOOP asked_of_me\nsummary: Review the Redis fallback patch\n'
            'cite: [3] "can you review the Redis fallback patch before Friday"\nresolved: no\nresolved_cite: -')
CLOSE_SHAPE = Shape("loops_close", records=(Record("UPDATE", "updates", F("loop", "int", hint="loop number"), (
    F("resolved", "bool"), F("cite", "cite", required=False))),),
    example='UPDATE 1\nresolved: yes\ncite: [4] "I merged the fix this morning"')
```

`archie/derive/cross_close.py` (imports `F, Shape`):

```python
SHAPE = Shape("loops_cross",
              fields=(F("done", "bool"), F("strength", "choice", required=False, choices=("strong", "weak")),
                      F("cite", "cite", required=False)),
              example='done: yes\nstrength: strong\ncite: [2] "Approved the Redis fallback patch"')
```

`archie/derive/enrich.py` (imports `F, Record, Shape`):

```python
SHAPE = Shape("people_facts", records=(Record("FACT", "facts", F("text", hint="short phrase"),
                                              (F("cite", "cite"),)),),
              example='FACT Product manager for auth\ncite: [2] "I\'m the PM for auth"')
```

- [ ] **Step 4: Run the new tests and the full suite**

Run: `uv run pytest tests/unit/test_shapes.py -q && uv run pytest -q`
Expected: test_shapes all pass (21 tests); full suite 317 passed, 4 xfailed (285 + 11 from Tasks 1–2 + 21).

- [ ] **Step 5: Commit**

```bash
git add archie/ask archie/derive tests/unit/test_shapes.py
git commit -m "Declare a line-format Shape at each model call site"
```

---

### Task 4: Switch every call site from JSON schemas to shapes

**Files:**
- Modify: `archie/llm/backend.py` (Protocol, `TextBackend`, `FakeBackend`)
- Modify: the 10 call-site modules from Task 3 and `archie/derive/jira_loops.py`
- Modify prompts: `archie/llm/prompts/answer.md`, `route.md`, `correct.md`, `loop_update.md`, `loops_close.md`, `loops_cross.md`, `loops_extract.md`, `notes_actions.md`, `people_facts.md`, `remember.md`
- Modify tests: `tests/support/fixtures.py`, `tests/support/heuristic_llm.py`, `tests/unit/test_ask.py:37`, `tests/unit/test_who.py:57`, `tests/unit/test_backend.py`
- Test: `tests/unit/test_backend.py`, `tests/unit/test_ask.py`

**Interfaces:**
- Consumes: all `*SHAPE` constants from Task 3.
- Produces: `Backend.complete(system: str, user: str, shape: Shape, tier: str = "fast") -> dict`; `TextBackend` with abstract `generate(system, user, tier) -> str` and concrete `complete`; `FakeBackend.calls` entries are `{"system", "user", "shape", "tier"}`; a `str` reply to `FakeBackend` goes through `shape.parse`. `by_schema(**handlers)` dispatches on `shape.name` (name kept so 142 call sites don't change).

Between this task and Task 5 the live app has no working backend (Claude takes schemas). Tests pass at every commit.

- [ ] **Step 1: Write the failing tests**

Replace the two FakeBackend tests at the top of `tests/unit/test_backend.py` (leave the Claude tests; Task 5 deletes them) with:

```python
from archie.llm.backend import ClaudeCodeBackend, FakeBackend, LLMError, TextBackend, make_backend
from archie.llm.shape import F, Shape

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
SHAPE = Shape("t", fields=(F("a"),), example="a: x")


def test_fake_backend_replays_and_records():
    fb = FakeBackend([{"a": "1"}])
    assert fb.complete("sys", "user", SHAPE) == {"a": "1"}
    assert fb.calls[0]["user"] == "user" and fb.calls[0]["shape"] is SHAPE


def test_fake_backend_accepts_a_function():
    fb = FakeBackend(lambda system, user, shape, tier: {"a": tier})
    assert fb.complete("s", "u", SHAPE, tier="strong") == {"a": "strong"}


def test_fake_backend_parses_text_replies():
    assert FakeBackend(["a: hello"]).complete("s", "u", SHAPE) == {"a": "hello"}
    with pytest.raises(LLMError, match="missing `a`"):
        FakeBackend(["nothing useful"]).complete("s", "u", SHAPE)


class Scripted(TextBackend):
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def generate(self, system, user, tier="fast"):
        self.seen.append((system, user, tier))
        return self.replies.pop(0)


def test_text_backend_appends_instructions_and_parses():
    b = Scripted(["a: ok"])
    assert b.complete("Be brief.", "hi", SHAPE, tier="strong") == {"a": "ok"}
    system, user, tier = b.seen[0]
    assert system.startswith("Be brief.\n\n") and "not JSON" in system and user == "hi" and tier == "strong"


def test_text_backend_retries_once_then_explains():
    b = Scripted(["oops", "a: fixed"])
    assert b.complete("s", "hi", SHAPE) == {"a": "fixed"}
    assert "couldn't be read: missing `a`" in b.seen[1][1]
    with pytest.raises(LLMError, match="reply couldn't be read \\(missing `a`\\)"):
        Scripted(["oops", "still oops"]).complete("s", "hi", SHAPE)
```

Add an end-to-end test to `tests/unit/test_ask.py` (text replies go through route parse, claims parse and the real verifier). Put it after `test_no_hits_says_so_without_calling_synthesis`; `seeded`, `make_ctx`, `ask`, `render` and `by_schema` are already imported there:

```python
def test_text_replies_run_through_the_real_parser_and_verifier(tmp_path):
    route_text = "intent: search\npeople: -\nsince: -\nuntil: -\ntopic: Priya\nmeeting: -\ntext: -"
    answer_text = ('SUMMARY\nPriya is the PM for auth. [1] "Priya is the PM for auth"\n'
                   'Made up. [1] "nothing like this exists"')
    ctx = seeded(tmp_path, by_schema(route=route_text, answer=answer_text))
    ans = ask(ctx, "who is priya")
    assert [c.text for c in ans.summary] == ["Priya is the PM for auth."]
    assert ans.dropped == 1
```

(`seeded()` writes `DOSSIER = "## Priya Sharma\nPriya is the PM for auth. Likes data.\n"`, so the first quote verifies and the second is dropped.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_backend.py tests/unit/test_ask.py -q`
Expected: FAIL with `ImportError: cannot import name 'TextBackend'`

- [ ] **Step 3: Backend plumbing**

In `archie/llm/backend.py`, update the module docstring's first line to `"""One LLM interface: text in, a line-format reply out, parsed and checked by code. No tools, ever (DESIGN §9).`, add `from archie.llm.shape import Shape` to the imports, and replace `Backend` and `FakeBackend` with:

```python
class Backend(Protocol):
    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict: ...


class TextBackend:
    """Subclasses implement generate(). complete() adds the shape's format instructions,
    parses and checks the reply, and asks once more if it couldn't be read."""

    def generate(self, system: str, user: str, tier: str = "fast") -> str:
        raise NotImplementedError

    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict:
        system = f"{system}\n\n{shape.instructions()}"
        out, problems = shape.parse(self.generate(system, user, tier))
        if not problems:
            return out
        retry = f"{user}\n\nYour last reply couldn't be read: {'; '.join(problems)}. Reply again in the format."
        out, problems = shape.parse(self.generate(system, retry, tier))
        if problems:
            raise LLMError(f"the model's reply couldn't be read ({'; '.join(problems[:3])})")
        return out


class FakeBackend:
    """For tests: replays canned replies (or calls fn(system, user, shape, tier)); records calls.
    A dict reply is returned as is; a str reply goes through the real parse-and-check."""

    def __init__(self, replies: list[dict | str] | Callable[[str, str, Shape, str], dict | str]):
        self.replies = replies
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict:
        self.calls.append({"system": system, "user": user, "shape": shape, "tier": tier})
        if callable(self.replies):
            reply = self.replies(system, user, shape, tier)
        elif not self.replies:
            raise LLMError("FakeBackend has no replies left")
        else:
            reply = self.replies.pop(0)
        if isinstance(reply, str):
            out, problems = shape.parse(reply)
            if problems:
                raise LLMError(f"the model's reply couldn't be read ({'; '.join(problems[:3])})")
            return out
        return reply
```

- [ ] **Step 4: Test helpers dispatch on the shape name**

`tests/support/fixtures.py`:

```python
def by_schema(**handlers):
    """FakeBackend reply fn that dispatches on the shape's name."""

    def reply(system, user, shape, tier):
        fn = handlers[shape.name]
        return fn(system, user, shape, tier) if callable(fn) else fn

    return reply
```

`tests/support/heuristic_llm.py`, method `complete`:

```python
    def complete(self, system: str, user: str, shape, tier: str = "fast") -> dict:
        title = shape.name
        self.calls.append(title)
        self.prompts.append((title, user))
        return getattr(self, f"_{title}")(system, user)
```

`tests/unit/test_ask.py:37` and `tests/unit/test_who.py:57`: replace `[c["schema"]["title"] for c in fb.calls]` with `[c["shape"].name for c in fb.calls]`.

- [ ] **Step 5: Call sites pass shapes; delete the JSON schemas**

In each file, delete the JSON-schema constant (and `_CLAIM`, `_NULLABLE` where they only served it) and pass the shape:

| File | Delete | Change the call to |
|---|---|---|
| `archie/ask/router.py` | `_NULLABLE`, `SCHEMA` | `ctx.backend.complete(system, question, SHAPE, tier="fast")` |
| `archie/ask/synthesize.py` | `_CLAIM`, `SCHEMA` | `ctx.backend.complete(system, user, SHAPE, tier=tier)` |
| `archie/ask/intents/clarify.py` | `SCHEMA` | `..., f"Questions:\n{listing}\n\nReply: {question}", SHAPE, tier="fast")` |
| `archie/ask/intents/correct.py` | `SCHEMA` | `ctx.backend.complete(load_prompt("correct", ...), question, SHAPE)` |
| `archie/ask/intents/loops.py` | `UPDATE_SCHEMA` | `..., UPDATE_SHAPE, tier="fast")` |
| `archie/ask/intents/notes.py` | `SCHEMA` | `ctx.backend.complete(system, f"Notes:\n{text}", SHAPE, tier="fast")` |
| `archie/ask/intents/remember.py` | `SCHEMA` | `ctx.backend.complete(load_prompt("remember", ...), question, SHAPE)` |
| `archie/derive/loops.py` | `EXTRACT_SCHEMA`, `CLOSE_SCHEMA` | `CLOSE_SHAPE` in `_close`, `EXTRACT_SHAPE` in `_extract` |
| `archie/derive/jira_loops.py` | — | import `CLOSE_SHAPE, EXTRACT_SHAPE` instead of `CLOSE_SCHEMA, EXTRACT_SCHEMA`; use them in both calls |
| `archie/derive/cross_close.py` | `SCHEMA` | `ctx.backend.complete(system, user, SHAPE, tier="fast")` |
| `archie/derive/enrich.py` | `SCHEMA` | `..., f"Sources about {name}:\n\n{packet.render()}", SHAPE, tier="fast")` |

`jira_loops.py` import becomes:

```python
from archie.derive.loops import (CLOSE_SHAPE, EXTRACT_SHAPE, OPEN, Loop, _duplicate, _history, load_loops,
                                 save_loop)
```

Check nothing still refers to a schema: `grep -rn "SCHEMA\|\"title\":" archie --include=*.py` must print only `archie/index/db.py:SCHEMA_VERSION`.

- [ ] **Step 6: Prompt wording**

The format instructions now come from the shape, so remove JSON-specific wording:

`archie/llm/prompts/answer.md`: replace

```
Every claim needs at least one citation: the source number (`ref`) and a short quote
copied EXACTLY, word for word, from that source (8+ characters).
```

with

```
Every claim needs at least one citation: the source number and a short quote copied
EXACTLY, word for word, from that source (8+ characters).
```

and replace

```
- `summary`: 1–4 short plain-English sentences answering the question directly.
- `sections`: optional supporting details, each item one short fact.
```

with

```
- The summary: 1–4 short plain-English sentences answering the question directly.
- Sections: optional supporting details, each item one short fact.
```

and `- If the sources don't answer the question, return an empty summary.` with `- If the sources don't answer the question, leave the summary empty.`

`archie/llm/prompts/route.md`: replace

```
If more than one of these appears, put the first kind in `intent`/`params` and each other
kind in `also`, with `text` = the exact sentences of that part copied from the message.
Example: "I don't need to call Ken. I picked up the pizza. Sam is my neighbor." →
intent loop_update; also [{intent: remember, text: "Sam is my neighbor."}].
Leave `also` empty for a single request.
```

with

```
If more than one of these appears, put the first kind in `intent` and each other kind in
its own ALSO block, with `text` = the exact sentences of that part copied from the message.
Example: "I don't need to call Ken. I picked up the pizza. Sam is my neighbor." → intent
loop_update, then `ALSO remember` with `text: Sam is my neighbor.`
Write no ALSO block for a single request.
```

`correct.md`: `Leave fields that don't apply null.` → `Write - for fields that don't apply.`

`loop_update.md`: `If you can't tell which item they mean, return an\nempty \`loops\` list.` → `If you can't tell which item they mean, write\n\`loops: -\`.`

`loops_close.md`: replace

```
For each open loop listed, return `resolved` true or false. When true, give `ref` (the
NEW message number) and `quote`: words copied EXACTLY from that message (8+ characters)
that show it is closed. When false, use ref 0 and an empty quote.
```

with

```
For each open loop listed, give `resolved` yes or no. When yes, give `cite`: the NEW
message number and words copied EXACTLY from that message (8+ characters) that show it
is closed. When no, write `cite: -`.
```

`loops_cross.md`: replace the `done` and `ref and quote` bullets with

```
- `done`: yes only if a source clearly shows this specific item was completed.
- `strength`: "strong" if it's unambiguous; "weak" if it probably refers to it.
- `cite`: the source number and words copied EXACTLY from it (8+ characters) that show
  it. Write `cite: -` when `done` is no.
```

`loops_extract.md`: replace

```
anyway, set `resolved` true and cite the resolving message.
```

with

```
anyway, set `resolved: yes` and give `resolved_cite` for the resolving message.
```

replace

```
- `ref`: the number of the message containing it, and `quote`: words copied EXACTLY from
  that message (8+ characters) that show the request or promise. If it has a deadline
```

with

```
- `cite`: the number of the message containing it and words copied EXACTLY from that
  message (8+ characters) that show the request or promise. If it has a deadline
```

and `Return an empty list when there are no loops.` with `Write NONE when there are no loops.`

`notes_actions.md`: `Return an empty list if there are none.` → `Write NONE if there are none.`

`people_facts.md`: replace

```
Refer to {me_name} as "you" ("your son", "your manager"). Each fact: a short phrase (`text`), the source number (`ref`), and a `quote` copied EXACTLY
from that source (8+ characters) that supports it. Only state what the sources show.
Return an empty list if they show nothing lasting.
```

with

```
Refer to {me_name} as "you" ("your son", "your manager"). Each fact: a short phrase after
FACT, then `cite`: the source number and words copied EXACTLY from that source (8+
characters) that support it. Only state what the sources show.
Write NONE if they show nothing lasting.
```

`remember.md`: replace each `or null` / `else null` with `or -` / `else -`, and `else []` (twice) with `else -`.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: 321 passed, 4 xfailed (317 + 3 new backend tests + 1 end-to-end; the two rewritten FakeBackend tests replace two existing ones). If a test that injected a schema-shaped dict reply fails, it is reading a key the shape now names differently: fix the shape (Task 3), not the handler.

- [ ] **Step 8: Update OKF, commit**

In `okf/components/llm.md`, change the description to `One method, Backend.complete(system, user, shape, tier) -> dict, with no tools. Replies use a line format parsed and checked by code. Includes the context packet and the citation verifier.` and add a bullet under the file list:

```markdown
- `shape.py`: each model call declares a `Shape` (fields, records, or cited claims). It writes the format instructions appended to the system prompt, parses the plain-text reply into the dict the caller uses, and reports problems; `TextBackend.complete` retries once on a problem. No JSON or schema is sent.
```

```bash
git add archie tests okf/components/llm.md
git commit -m "Use line-format shapes at every model call instead of JSON schemas"
```

---

### Task 5: Gemini backend; remove Claude

**Files:**
- Modify: `archie/llm/backend.py`, `archie/config.py`, `pyproject.toml`, `uv.lock`
- Test: `tests/unit/test_backend.py`

**Interfaces:**
- Consumes: `TextBackend` (Task 4), `archie.secrets.get_secret`, `KeychainWaiting`.
- Produces: `GeminiBackend(llm: dict, client=None)` implementing `generate(system, user, tier) -> str`; `make_backend(config) -> GeminiBackend`; `DEFAULTS["llm"]` per Global Constraints. Keychain key name `gemini-api-key` (used again by Task 6).

- [ ] **Step 1: Add the dependency**

Run: `uv add "google-genai>=2.28"`
Expected: `pyproject.toml` dependencies gain `google-genai>=2.28`; `uv.lock` updated.

- [ ] **Step 2: Write the failing tests**

In `tests/unit/test_backend.py`, delete every `ClaudeCodeBackend` test (`test_claude_code_*`, `test_make_backend_from_config`, `test_usage_limit_error_is_explained`), the `json` import and `SCHEMA`, change the import line to `from archie.llm.backend import FakeBackend, GeminiBackend, LLMError, TextBackend, make_backend`, and add:

```python
import threading
from types import SimpleNamespace

import httpx
from google.genai import errors

LLM = {"backend": "gemini", "models": {"fast": "flash-x", "strong": "pro-x"},
       "max_output_tokens": {"fast": 100, "strong": 900}, "thinking": {"fast": "low", "strong": "medium"}}


def reply(text, finish="STOP", block=None):
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish))
    return SimpleNamespace(text=text, candidates=[cand] if finish else [],
                           prompt_feedback=SimpleNamespace(block_reason=SimpleNamespace(name=block)) if block else None)


class Client:
    def __init__(self, result):
        self.result, self.calls = result, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_gemini_sends_system_model_cap_and_thinking():
    client = Client(reply("a: ok"))
    b = GeminiBackend(LLM, client=client)
    assert b.complete("Be brief.", "hi", SHAPE, tier="strong") == {"a": "ok"}
    model, contents, config = client.calls[0]
    assert model == "pro-x" and contents == "hi"
    assert config.system_instruction.startswith("Be brief.") and config.max_output_tokens == 900
    assert config.thinking_config.thinking_level.value == "MEDIUM"
    assert config.http_options.timeout == 300_000
    assert config.response_mime_type is None


def test_thinking_can_be_switched_off():
    client = Client(reply("a: ok"))
    GeminiBackend({**LLM, "thinking": {"fast": "off"}}, client=client).generate("s", "u", "fast")
    assert client.calls[0][2].thinking_config is None


@pytest.mark.parametrize("exc, words", [
    (errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}), "limit is reached"),
    (errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid"}}), "rejected the API key"),
    (errors.ClientError(404, {"error": {"status": "NOT_FOUND", "message": "no model"}}), "doesn't know the model 'flash-x'"),
    (errors.ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}}), "server error \\(503\\)"),
    (httpx.ReadTimeout("slow"), "didn't answer within 60 seconds"),
    (httpx.ConnectError("down"), "couldn't reach Gemini"),
])
def test_errors_are_explained(exc, words):
    with pytest.raises(LLMError, match=words):
        GeminiBackend(LLM, client=Client(exc)).generate("s", "u", "fast")


def test_empty_reply_is_explained():
    with pytest.raises(LLMError, match="blocked the request \\(SAFETY\\)"):
        GeminiBackend(LLM, client=Client(reply(None, finish=None, block="SAFETY"))).generate("s", "u")
    with pytest.raises(LLMError, match="cut off at the output limit"):
        GeminiBackend(LLM, client=Client(reply(None, finish="MAX_TOKENS"))).generate("s", "u")
    with pytest.raises(LLMError, match="empty reply"):
        GeminiBackend(LLM, client=Client(reply("  "))).generate("s", "u")


def test_missing_key_says_how_to_fix(monkeypatch):
    from archie import secrets

    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: None)
    with pytest.raises(LLMError, match="archie admin connect gemini"):
        GeminiBackend(LLM).generate("s", "u")


def test_keychain_wait_becomes_llm_error(monkeypatch):
    from archie import secrets

    def waiting(key, timeout=15):
        raise secrets.KeychainWaiting("waiting for Keychain permission")

    monkeypatch.setattr(secrets, "get_secret", waiting)
    with pytest.raises(LLMError, match="Keychain"):
        GeminiBackend(LLM).generate("s", "u")


def test_client_is_created_once_across_threads(monkeypatch):
    from google import genai

    from archie import secrets

    made = []
    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: "k")
    monkeypatch.setattr(genai, "Client", lambda api_key: made.append(api_key) or Client(reply("a: ok")))
    b = GeminiBackend(LLM)
    threads = [threading.Thread(target=b.generate, args=("s", "u")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert made == ["k"]


def test_make_backend():
    assert isinstance(make_backend({"llm": LLM}), GeminiBackend)
    with pytest.raises(LLMError, match="llm.backend 'claude-code'"):
        make_backend({"llm": {**LLM, "backend": "claude-code"}})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_backend.py -q`
Expected: FAIL with `ImportError: cannot import name 'GeminiBackend'`

- [ ] **Step 4: Implement `GeminiBackend`; delete Claude**

In `archie/llm/backend.py`: delete `_run`, `Runner`, `ClaudeCodeBackend`, and the now-unused imports (`json`, `os`, `subprocess`, `tempfile`); add `import threading`. Update the docstring's second paragraph to `Model tiers: "fast" (routing, extraction) and "strong" (briefings, conflicts, handovers). Backend: Gemini (google-genai); the key is in the Keychain as "gemini-api-key".` Add:

```python
TIMEOUT_S = {"fast": 60, "strong": 300}


class GeminiBackend(TextBackend):
    """The Gemini API through google-genai: plain text in and out, no tools."""

    def __init__(self, llm: dict, client=None):
        self.models = llm.get("models") or {}
        self.caps = llm.get("max_output_tokens") or {}
        self.thinking = llm.get("thinking") or {}
        self._client = client
        self._lock = threading.Lock()

    def client(self):
        with self._lock:
            if self._client is None:
                from google import genai

                from archie.secrets import KeychainWaiting, get_secret

                try:
                    key = get_secret("gemini-api-key")
                except KeychainWaiting as exc:
                    raise LLMError(str(exc)) from exc
                if not key:
                    raise LLMError("Archie has no Gemini API key. Run `archie admin connect gemini`")
                self._client = genai.Client(api_key=key)
            return self._client

    def generate(self, system: str, user: str, tier: str = "fast") -> str:
        import httpx
        from google.genai import errors, types

        model = self.models.get(tier) or self.models.get("fast")
        level = str(self.thinking.get(tier) or "low").upper()
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=int(self.caps.get(tier) or 2048),
            thinking_config=None if level == "OFF" else types.ThinkingConfig(thinking_level=level),
            http_options=types.HttpOptions(timeout=TIMEOUT_S.get(tier, 60) * 1000),
        )
        try:
            resp = self.client().models.generate_content(model=model, contents=user, config=config)
        except errors.APIError as exc:
            raise LLMError(_explain(exc, model)) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(f"Gemini didn't answer within {TIMEOUT_S.get(tier, 60)} seconds") from exc
        except httpx.TransportError as exc:
            raise LLMError("couldn't reach Gemini; check the network connection") from exc
        text = resp.text
        if text and text.strip():
            return text
        block = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
        if block:
            raise LLMError(f"Gemini blocked the request ({block.name})")
        finish = resp.candidates[0].finish_reason.name if resp.candidates else ""
        if finish == "MAX_TOKENS":
            raise LLMError("Gemini's reply was cut off at the output limit (llm.max_output_tokens in config.yaml)")
        raise LLMError("Gemini returned an empty reply")


def _explain(exc, model: str) -> str:
    message = str(getattr(exc, "message", "") or "")
    if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
        return ("Gemini's rate or quota limit is reached. Archie can still list items and plans without it, "
                "but can't write answers until then")
    if exc.code in (401, 403) or "api key" in message.lower():
        return "Gemini rejected the API key. Run `archie admin connect gemini` to store a new one"
    if exc.code == 404:
        return f"Gemini doesn't know the model {model!r}: check llm.models in config.yaml"
    if exc.code and exc.code >= 500:
        return f"Gemini had a server error ({exc.code}); try again shortly"
    return f"Gemini reported an error: {exc.code} {message}".strip()


def make_backend(config: dict) -> Backend:
    llm = config["llm"]
    if llm.get("backend") == "gemini":
        return GeminiBackend(llm)
    raise LLMError(f"unknown llm.backend {llm.get('backend')!r} in config.yaml (only 'gemini' is supported)")
```

(`make_backend` replaces the old one.)

In `archie/config.py`, replace the `llm` default with:

```python
    "llm": {
        "backend": "gemini",
        "parallel": 4,
        "models": {"fast": "gemini-3.7-flash", "strong": "gemini-3.1-pro-preview"},
        "max_output_tokens": {"fast": 2048, "strong": 8192},
        "thinking": {"fast": "low", "strong": "medium"},
    },
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_backend.py -q && uv run pytest -q`
Expected: backend tests pass; full suite 329 passed, 4 xfailed (321 − 5 removed Claude tests + 13 new Gemini tests). `grep -rni "claude" archie` prints nothing.

- [ ] **Step 6: Update OKF, commit**

In `okf/components/llm.md`, replace the `ClaudeCodeBackend` bullet, the haiku/sonnet tiers bullet and the "`anthropic` SDK backend is not built yet" bullet with:

```markdown
  - `GeminiBackend` calls the Gemini API through `google-genai` with plain text in and out (no tools). It reads the key from the Keychain item `gemini-api-key` once per process, caps output tokens per tier (`llm.max_output_tokens`), sets a thinking level per tier (`llm.thinking`, `off` to omit), and turns quota, key, model, server, network, timeout, safety and empty-reply failures into one-sentence `LLMError`s.
  - Tiers: `fast` maps to `gemini-3.7-flash` and `strong` to `gemini-3.1-pro-preview` by default (`llm.models`).
```

```bash
git add archie/llm/backend.py archie/config.py pyproject.toml uv.lock tests/unit/test_backend.py okf/components/llm.md
git commit -m "Switch the LLM backend to Gemini and remove the Claude backend"
```

---

### Task 6: `connect gemini`, doctor check, and docs

**Files:**
- Modify: `archie/cli.py`, `archie/doctor.py`, `tests/unit/test_doctor.py`, `tests/unit/test_cli.py`
- Modify docs: `README.md`, `docs/DESIGN.md` (§9), `okf/components/doctor.md`, `okf/components/cli.md`, `okf/log.md`

**Interfaces:**
- Consumes: Keychain key name `gemini-api-key` (Task 5); `archie.secrets.set_secret`, `get_secret`, `KeychainWaiting`.
- Produces: `doctor.check_gemini() -> Check`; `cli.connect_gemini() -> int`; `archie admin connect gemini`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_doctor.py`, replace `test_claude_and_gh_checks` with:

```python
def test_gemini_and_gh_checks(monkeypatch):
    from archie import secrets

    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: None)
    ok, msg = doctor.check_gemini()
    assert not ok and "archie admin connect gemini" in msg
    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: "k" if key == "gemini-api-key" else None)
    assert doctor.check_gemini() == (True, "gemini: API key stored")
    fail = lambda *a, **k: type("P", (), {"returncode": 1})()  # noqa: E731
    assert "gh auth login" in doctor.check_gh(run=fail)[1]
```

Add to `tests/unit/test_cli.py`:

```python
def test_connect_gemini_stores_the_key(monkeypatch, capsys):
    import getpass

    from archie import secrets

    saved = {}
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "  key-123 \n")
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: saved.update({k: v}))
    assert cli.main(["admin", "connect", "gemini"]) == 0
    assert saved == {"gemini-api-key": "key-123"}
    assert "Keychain" in capsys.readouterr().out


def test_connect_gemini_with_no_key_changes_nothing(monkeypatch):
    import getpass

    from archie import secrets

    monkeypatch.setattr(getpass, "getpass", lambda prompt: "")
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: pytest.fail("should not save"))
    assert cli.main(["admin", "connect", "gemini"]) == 1
```

(Add `import pytest` to `tests/unit/test_cli.py` if it isn't imported.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_doctor.py tests/unit/test_cli.py -q`
Expected: FAIL (`check_gemini` missing; argparse rejects `gemini`).

- [ ] **Step 3: Implement**

`archie/doctor.py`: delete `check_claude` and the `shutil` import, add

```python
def check_gemini() -> Check:
    from archie.secrets import KeychainWaiting, get_secret

    try:
        ok = bool(get_secret("gemini-api-key"))
    except KeychainWaiting as exc:
        return False, str(exc)
    return (True, "gemini: API key stored") if ok else (False, "gemini: no API key: run `archie admin connect gemini`")
```

and in `run_checks` use `results = [check_me(home), check_gemini()]`.

`archie/cli.py`: add `archie admin connect gemini` to `USAGE`:

```python
USAGE = """\
usage: archie                 open Archie (the TUI)
       archie ask "question"  ask anything, e.g. archie ask "what should I work on next?"
       archie admin init|sync|rederive|reindex|status|doctor
       archie admin connect gemini
       archie admin connect google [--client client.json] [--import-token token.json]"""
```

In `cmd_connect`, change `choices=["google", "jira"]` to `choices=["google", "jira", "gemini"]` and add before the Jira branch:

```python
    if args.service == "gemini":
        return connect_gemini()
```

Add after `connect_jira`:

```python
def connect_gemini() -> int:
    import getpass

    from archie.secrets import set_secret

    key = getpass.getpass("Gemini API key (aistudio.google.com → Get API key): ").strip()
    if not key:
        print("No key entered; nothing changed.")
        return 1
    set_secret("gemini-api-key", key)
    print("Gemini API key saved in the Keychain.")
    return 0
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: 331 passed, 4 xfailed.

- [ ] **Step 5: Docs**

`README.md` Setup block: add after `uv run archie admin init`:

```
uv run archie admin connect gemini              # Gemini API key, stored in the Keychain
```

and in the **First launch** paragraph change `("archie", "google-token")` to `("archie", "google-token" or "gemini-api-key")`.

`docs/DESIGN.md` §9: replace from ```` ```python ```` through the `- **Citations by reference number.**` bullet's preceding line with:

````markdown
```python
class Backend(Protocol):
    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict: ...
```

`tier` is `fast` (routing, extraction) or `strong` (briefings, conflicts, handovers); config
maps each tier to a model.

- Text in, **a plain line format** out. Each call declares a `Shape` (fields, records, or
  cited claims). Code appends the shape's format instructions to the system prompt,
  parses the reply into a dict, checks it, and asks once more if it couldn't be read. No
  JSON schema is sent: schema-forced output costs tokens and is less reliable. **No
  tools**, no file access and no network beyond the model call itself.
- **Backends:**
  - `gemini` (default): the Gemini API through `google-genai`. The key is in the Keychain
    (`gemini-api-key`, set with `archie admin connect gemini`). Output tokens are capped
    per tier and thinking is kept low for `fast`.
  - `fake`: replays canned responses, for tests.
````

`okf/components/doctor.md`: replace `- The \`claude\` CLI is on PATH.` with `- A Gemini API key is in the Keychain (\`gemini-api-key\`).`

`okf/components/cli.md`: in the doctor sentence, replace `the claude CLI` with `the Gemini API key`, and add `\`archie admin connect gemini\` stores the Gemini API key in the Keychain.` after it.

`okf/log.md`: add at the top of `## 2026-10-03`:

```markdown
- The model backend is now Gemini (`google-genai`), and replies use a plain line format instead of JSON schemas (`archie/llm/shape.py`). Each call declares a `Shape`; code writes the format instructions, parses and checks the reply, and retries once. Schema-forced JSON cost tokens and was less reliable. The Claude backend is removed (it's in git history). Spec: `docs/superpowers/specs/2026-10-03-gemini-line-format-design.md`.
```

- [ ] **Step 6: Check OKF and graphify, commit**

Run: `python3 scripts/okf_check.py`
Expected: no errors.

Docs changed, so per CLAUDE.md the graphify docs refresh (`/graphify . --update`) needs an LLM session; note it for the user if it can't run here. The pre-commit hook runs `graphify update .` for code.

```bash
git add archie/cli.py archie/doctor.py tests/unit/test_doctor.py tests/unit/test_cli.py README.md docs/DESIGN.md okf
git commit -m "Add archie admin connect gemini and a doctor check; document the Gemini backend"
```

---

### Task 7: Live check

Needs the user's Gemini API key. No code unless a check fails.

- [ ] **Step 1: Store the key and run doctor**

The user runs `uv run archie admin connect gemini` (hidden input), then:

Run: `uv run archie admin doctor`
Expected: `✓ gemini: API key stored`.

- [ ] **Step 2: Confirm the model names exist**

Run: `uv run python -c "from google import genai; from archie.secrets import get_secret; c = genai.Client(api_key=get_secret('gemini-api-key')); print(sorted(m.name for m in c.models.list() if 'gemini' in m.name))"`
Expected: the list includes `models/gemini-3.7-flash` and `models/gemini-3.1-pro-preview`. If not, pick the closest current Flash and Pro names, update `DEFAULTS["llm"]["models"]` in `archie/config.py` and the README/OKF mentions, and commit that change.

- [ ] **Step 3: Three real questions**

Run each and read the output:

```bash
uv run archie ask "Did HeadphonesRUs reply about my earbud?" --sources   # route + answer with citations
uv run archie ask "Tell me about Goodspouse"                                # who intent, strong tier
uv run archie ask "Sam is my neighbor."                                 # remember (writes people/; check the dossier)
```

Expected: a cited summary, a who answer, and "Got it. I'll remember: …". Then check the last three lines of `~/.archie/logs/usage.jsonl`: no `error`, and `dropped` counts no higher than in comparable Claude-era answers. If `remember` created a test dossier for Sam that the user doesn't want, tell them where it is rather than deleting it.

- [ ] **Step 4: Record the result**

Add one line to `okf/log.md` under 2026-10-03 stating the live check result (models used, whether the three questions answered, any dropped claims), then commit:

```bash
git add okf/log.md
git commit -m "Log the Gemini live check"
```

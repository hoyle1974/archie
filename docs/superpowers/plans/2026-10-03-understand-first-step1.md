# Understand First, Step 1: Understanding and Follow-ups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the menu router with one "understanding" call that sees the recent conversation and Archie's open questions and splits each message into parts, and make follow-ups work ("them", "show 1", "really?"), so vignette O passes.

**Architecture:** `ask()` tries code-only shortcuts first (quick questions, "show N", "really?", a plain yes/no), otherwise calls `understand()` (one fast-tier call, line-format `PART` records), checks the reply in code, and `dispatch()`es each part to the existing intent handlers. Every finished exchange is appended to `~/.archie/state/conversation.jsonl`, which the next message reads. Tellings and instructions keep using the existing `remember`, `loop_update`, `correct` and `notes` code until steps 2–3 replace them.

**Tech Stack:** Python 3.11+, pytest, the existing line-format `Shape` (`archie/llm/shape.py`), `FakeBackend` and `HeuristicLLM` for tests.

**Spec:** `docs/superpowers/specs/2026-10-03-understand-first-design.md` (this plan is build step 1 of §6; steps 2–5 get their own plans).

## Global Constraints

- Files under `~/.archie/` are the source of truth; the conversation lives in `state/conversation.jsonl`.
- One fast-tier model call to understand a message; it replaces the router's call. Replies use the line format, not JSON.
- The model's factual claims keep `[n] "quote"` citations and the verifier; the understanding call states no facts.
- The user's own words are never checked against the archive.
- Archie never sends, posts or replies. A `send` instruction gets exactly: `I can't send anything; I only read.`
- Conversation memory: the last 3 exchanges, oldest first, chained by gaps of at most 30 minutes (including the gap from the newest to now). The file keeps the last 200 entries.
- Shape name is `understand`; record keyword is `PART`; kinds are `question`, `tell`, `instruct`, `answer`, `unclear`.
- Tests are rewritten to the new reply format. No adapter that translates old router replies.
- Answers open with a plain-English summary; IDs and paths never lead (the "show N" reply leads with the source label, the path comes last).
- Before every commit: update the OKF bundle when structure changes (Task 5 does it for this plan); never bypass the pre-commit hook.

## Review Focus

- A multi-line pasted message whose lines look like `key: value` ("Topic: hiring plan") must not change a part's fields, and the whole message must reach the notes handler. → Task 2 (shape test) and Task 3 (notes test).
- The model returns a part whose `text` isn't in the message, or a `resolved` question that names someone nobody mentioned. → falls back to the message's own words. Task 2 tests.
- A damaged line in `conversation.jsonl` (a crash mid-write, a hand edit) is skipped, never crashes `ask`. → Task 1 test.
- "really?" with no recent conversation, or right after another "really?", must not loop forever; it's handled as a normal message. → Task 4 test.
- "show 3" when the last answer had two sources, or the last answer had none (help text), says so plainly. → Task 4 test.

---

### Task 1: Conversation memory

**Files:**
- Create: `archie/ask/conversation.py`
- Modify: `archie/ask/render.py` (add `citations_of`)
- Test: `tests/unit/test_conversation.py`

**Interfaces:**
- Produces:
  - `conversation.append(home: Home, entry: dict) -> None`
  - `conversation.load(home: Home) -> list[dict]`
  - `conversation.recent(home: Home, now: datetime) -> list[dict]` (oldest first, at most 3)
  - `conversation.FILE = "state/conversation.jsonl"`, `KEEP = 200`, `RECENT = 3`, `WINDOW = timedelta(minutes=30)`
  - `render.citations_of(answer: Answer) -> list[dict]`, each `{"n": int, "file": str, "chunk": str, "label": str, "quote": str}`, numbered exactly as `render()` numbers `[n]`
  - An entry is `{"ts": iso str, "said": str, "resolved": str | None, "summary": str, "citations": list[dict]}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_conversation.py
from datetime import datetime, timedelta, timezone

from archie.ask import conversation
from archie.ask.answer import Answer, Section
from archie.ask.render import citations_of, render
from archie.llm.verify import Citation, Claim
from archie.store.home import init_home

T0 = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)


def entry(said, at):
    return {"ts": at.isoformat(), "said": said, "resolved": None, "summary": "", "citations": []}


def test_recent_is_the_last_three_oldest_first(tmp_path):
    home = init_home(tmp_path / "h")
    for i in range(5):
        conversation.append(home, entry(f"q{i}", T0 + timedelta(minutes=i)))
    assert [e["said"] for e in conversation.recent(home, T0 + timedelta(minutes=6))] == ["q2", "q3", "q4"]


def test_a_quiet_half_hour_starts_fresh(tmp_path):
    home = init_home(tmp_path / "h")
    conversation.append(home, entry("old topic", T0))
    conversation.append(home, entry("new topic", T0 + timedelta(minutes=45)))
    assert [e["said"] for e in conversation.recent(home, T0 + timedelta(minutes=46))] == ["new topic"]
    assert conversation.recent(home, T0 + timedelta(minutes=80)) == []


def test_the_file_keeps_the_last_200(tmp_path):
    home = init_home(tmp_path / "h")
    for i in range(205):
        conversation.append(home, entry(f"q{i}", T0))
    saved = conversation.load(home)
    assert len(saved) == 200 and saved[0]["said"] == "q5"


def test_a_damaged_line_is_skipped(tmp_path):
    home = init_home(tmp_path / "h")
    conversation.append(home, entry("fine", T0))
    with (home / conversation.FILE).open("a") as fh:
        fh.write('{"ts": "2026-10-03T18:01\n')
    assert [e["said"] for e in conversation.load(home)] == ["fine"]
    assert [e["said"] for e in conversation.recent(home, T0 + timedelta(minutes=2))] == ["fine"]


def test_citations_are_numbered_like_the_rendered_answer():
    a = Citation(1, "people/a.md", "c0", "alpha quote here", "A (dossier)")
    b = Citation(2, "sources/gmail/t.json", "c3", "beta quote here", "Email, Oct 2")
    ans = Answer(summary=[Claim("First.", [b])], sections=[Section("More", [Claim("Second.", [a, b])])])
    assert "First. [1]" in render(ans) and "Second. [2][1]" in render(ans)
    assert citations_of(ans) == [
        {"n": 1, "file": "sources/gmail/t.json", "chunk": "c3", "label": "Email, Oct 2", "quote": "beta quote here"},
        {"n": 2, "file": "people/a.md", "chunk": "c0", "label": "A (dossier)", "quote": "alpha quote here"}]
    assert citations_of(Answer(plain="help text")) == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest -q tests/unit/test_conversation.py`
Expected: FAIL with `ImportError: cannot import name 'conversation'`.

- [ ] **Step 3: Write `archie/ask/conversation.py`**

```python
"""Conversation memory for `ask` (state/conversation.jsonl). Each finished exchange keeps the
user's words, the question as understood, the answer's summary and its numbered citations.
Follow-ups ("show 1", "really?", "them") read the recent ones."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from archie.store.files import atomic_write
from archie.store.home import Home

FILE = "state/conversation.jsonl"
KEEP = 200
RECENT = 3
WINDOW = timedelta(minutes=30)


def load(home: Home) -> list[dict]:
    path = home / FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and "ts" in item:
            out.append(item)
    return out


def append(home: Home, entry: dict) -> None:
    entries = (load(home) + [entry])[-KEEP:]
    atomic_write(home / FILE, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))


def _when(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def recent(home: Home, now: datetime) -> list[dict]:
    """The last few exchanges, oldest first. A gap of more than 30 minutes (between two
    exchanges, or since the newest) ends the conversation, so an old topic isn't pulled in."""
    out: list[dict] = []
    later = now
    for entry in reversed(load(home)):
        when = _when(entry)
        if when is None or later - when > WINDOW or len(out) == RECENT:
            break
        out.append(entry)
        later = when
    return list(reversed(out))
```

- [ ] **Step 4: Add `citations_of` to `archie/ask/render.py`** (after `render`)

```python
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
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest -q tests/unit/test_conversation.py`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add archie/ask/conversation.py archie/ask/render.py tests/unit/test_conversation.py
git commit -m "Add conversation memory for ask (state/conversation.jsonl)"
```

---

### Task 2: The understanding call

**Files:**
- Create: `archie/ask/understand.py`, `archie/llm/prompts/understand.md`
- Modify: `archie/llm/shape.py:176-177` (record fields: first value wins)
- Test: `tests/unit/test_understand.py`, `tests/unit/test_shape.py`, `tests/unit/test_shapes.py`

**Interfaces:**
- Consumes: entry dicts from Task 1 (`said`, `resolved`, `summary`, `citations[].label`, `citations[].n`).
- Produces:
  - `understand.Part` dataclass: `kind: str, text: str, resolved: str | None, intent: str | None, params: dict, fact, about, question: int | None, action, target, wanted, options: list[int], ask`
  - `Part.params` keys: `people` (list), `since`, `until`, `topic`, `meeting`, `text` (the `notes` field)
  - `understand.understand(ctx, message: str, recent: list[dict], open_qs: list[dict]) -> list[Part]`
  - `understand.checked(raw: list[dict], message: str, recent: list[dict], open_qs: list[dict]) -> list[Part]`
  - `understand.prompt_input(message, recent, open_qs) -> str` (ends with `Message: <message>`)
  - `understand.SHAPE` (name `understand`), `KINDS`, `FACTS`, `ACTIONS`, `QUESTION_INTENTS` (dict name → help text)

- [ ] **Step 1: Write the failing shape test** (append to `tests/unit/test_shape.py`)

```python
def test_lines_inside_a_record_value_cannot_override_its_fields():
    from archie.llm.shape import F, Record, Shape

    s = Shape("t", records=(Record("PART", "parts", F("kind"), (F("topic", required=False), F("notes", required=False))),))
    out, problems = s.parse("PART question\ntopic: -\nnotes: Redis approved.\nTopic: hiring plan")
    assert problems == [] and out["parts"] == [{"kind": "question", "topic": None, "notes": "Redis approved."}]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest -q tests/unit/test_shape.py::test_lines_inside_a_record_value_cannot_override_its_fields`
Expected: FAIL (`topic` becomes `'hiring plan'`).

- [ ] **Step 3: Make record fields first-value-wins in `archie/llm/shape.py`**

Replace:

```python
        if blocks and key in {f.name for f in blocks[-1][0].fields}:
            blocks[-1][1][key] = value
```

with:

```python
        if blocks and key in {f.name for f in blocks[-1][0].fields}:
            blocks[-1][1].setdefault(key, value)  # a later look-alike line (pasted text) can't override
```

- [ ] **Step 4: Run the shape tests**

Run: `uv run pytest -q tests/unit/test_shape.py`
Expected: all pass.

- [ ] **Step 5: Write the failing understanding tests**

```python
# tests/unit/test_understand.py
from archie.ask.understand import Part, checked, prompt_input, understand
from archie.llm.backend import FakeBackend
from tests.support.fixtures import make_ctx

RECENT = [{"ts": "2026-10-01T16:00:00+00:00", "said": "did Status reply about my earbud?", "resolved": None,
           "summary": "HeadphonesRUs offered a replacement right earbud. [1]",
           "citations": [{"n": 1, "file": "people/status_audio.md", "chunk": "c0", "label": "HeadphonesRUs (dossier)",
                          "quote": "offering a replacement right earbud"}]}]
WHO = [{"id": "q1", "kind": "who_is", "text": "Who is a@b.co? Tell me, e.g. \"a@b.co is my plumber\".",
        "status": "open"}]


def test_text_reply_becomes_parts(tmp_path):
    reply = ("PART instruct\ntext: I picked up the pizza.\naction: loop_done\n"
             "PART tell\ntext: Sam is my neighbor.\nfact: person\nabout: Sam")
    ctx = make_ctx(tmp_path, FakeBackend([reply]))
    parts = understand(ctx, "I picked up the pizza. Sam is my neighbor.", [], [])
    assert [(p.kind, p.text, p.action, p.fact) for p in parts] == [
        ("instruct", "I picked up the pizza.", "loop_done", None), ("tell", "Sam is my neighbor.", None, "person")]
    assert ctx.backend.calls[0]["shape"].name == "understand" and ctx.backend.calls[0]["tier"] == "fast"


def test_one_part_always_carries_the_whole_message():
    message = "notes from the design review:\nRedis approved.\nI need to update the runbook."
    [p] = checked([{"kind": "instruct", "text": "notes from the design review:", "action": "notes"}], message, [], [])
    assert p.text == message


def test_part_words_not_in_the_message_fall_back_to_the_message():
    message = "I left.  Sam is my neighbor."
    parts = checked([{"kind": "instruct", "text": "invented words", "action": "loop_done"},
                     {"kind": "tell", "text": "Sam is my neighbor.", "fact": "person"}], message, [], [])
    assert [p.text for p in parts] == [message, "Sam is my neighbor."]


def test_resolved_may_only_use_names_someone_said():
    ok = {"kind": "question", "text": "do you see the message I sent them?", "intent": "search",
          "resolved": "Do you see the message I sent HeadphonesRUs about the earbud?"}
    made_up = {**ok, "resolved": "Do you see the message I sent Bose about the earbud?"}
    assert checked([ok], ok["text"], RECENT, [])[0].resolved == ok["resolved"]
    assert checked([made_up], ok["text"], RECENT, [])[0].resolved is None
    assert checked([ok], ok["text"], [], [])[0].resolved is None  # nothing recent said "HeadphonesRUs"


def test_answer_to_a_question_that_does_not_exist_becomes_a_question():
    [p] = checked([{"kind": "answer", "text": "it's my plumber", "question": 4}], "it's my plumber", [], WHO)
    assert (p.kind, p.question) == ("question", None)
    [p] = checked([{"kind": "answer", "text": "it's my plumber", "question": 1}], "it's my plumber", [], WHO)
    assert (p.kind, p.question) == ("answer", 1)


def test_no_parts_means_search_the_whole_message():
    assert checked([], "zebras?", [], []) == [Part(kind="question", text="zebras?", intent="search",
                                                   params={"people": [], "since": None, "until": None,
                                                           "topic": None, "meeting": None, "text": None})]


def test_the_model_sees_the_conversation_and_open_questions_and_the_message_last():
    text = prompt_input("do you see the message I sent them?", RECENT, WHO)
    assert "You: did Status reply about my earbud?" in text
    assert "Archie: HeadphonesRUs offered a replacement right earbud. [1]" in text
    assert "Sources: [1] HeadphonesRUs (dossier)" in text
    assert "1. Who is a@b.co?" in text
    assert text.endswith("Message: do you see the message I sent them?")
    assert "Recent conversation" not in prompt_input("hi", [], [])
```

- [ ] **Step 6: Update `tests/unit/test_shapes.py`** so the shape list uses the new shape (the router's shape is deleted in Task 3)

Replace `from archie.ask.router import SHAPE as ROUTE` with `from archie.ask.understand import SHAPE as UNDERSTAND`, replace `ROUTE` with `UNDERSTAND` in `ALL`, replace `"route"` with `"understand"` in the expected names, and replace `test_route` with:

```python
def test_understand():
    out, problems = UNDERSTAND.parse("PART question\ntext: who is Ken?\nintent: who\npeople: Ken\n"
                                     "PART tell\ntext: Sam is my neighbor.\nfact: person\nabout: Sam")
    assert problems == []
    assert [(p["kind"], p["text"], p["intent"], p["people"], p["fact"]) for p in out["parts"]] == [
        ("question", "who is Ken?", "who", ["Ken"], None), ("tell", "Sam is my neighbor.", None, [], "person")]
```

- [ ] **Step 7: Run them to see them fail**

Run: `uv run pytest -q tests/unit/test_understand.py tests/unit/test_shapes.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'archie.ask.understand'`.

- [ ] **Step 8: Write `archie/llm/prompts/understand.md`**

```markdown
You read messages for Archie, a personal work-memory assistant for {me_name}. The current
local time is {now} ({weekday}). You don't answer. You work out what the message is and
split it into parts.

Each part is one of:
- question: the user wants to know something. Pick the intent that answers it.
- tell: the user is telling Archie something to remember. `fact`: person (who someone
  is: relationship, role, pronouns, other names, words to avoid), ignore (a sender is
  spam or should be ignored), unignore (stop ignoring one), or other. `about`: who or
  what it's about.
- instruct: the user wants Archie to do something. `action`: loop_done, loop_snooze,
  loop_dismiss or loop_reopen (an open item is finished, should wait until `until`, isn't
  a real item, or is open again); meeting_type (a meeting is a 1:1, standup or
  all-hands); merge_names (two names are one person); notes (the user is giving notes
  from a meeting); ignore or unignore (a sender); show_citation ("show 2");
  nudge_snooze; send (anything that sends: email, message, reply, invite, post); none
  (anything else, with a short verb phrase for it in `wanted`). `target`: which item, in
  the user's words.
- answer: a reply to one of Archie's open questions. `question`: its number.
- unclear: you can't tell what the user means, or more than one thing fits. `ask`: one
  short question back.

Intents for questions:
{intents}

Rules:
- `text` is the part's words copied exactly from the message. A message with one thing
  in it is one part.
- `resolved` (questions only): the question rewritten to stand alone, filling in "them",
  "her", "that" and similar from the recent conversation. Use only names and topics from
  the message or the conversation. If the message already stands alone or is about
  something new, write -.
- Parameters come from the message and, for follow-ups, the conversation: people (names
  or email addresses, not {me_name} themself), since and until (ISO dates; resolve "last
  week", "yesterday"; weeks run Monday to Sunday; quarters are calendar quarters), topic
  (a few words), meeting (words identifying a meeting).
- For notes, put the pasted note text in `notes`, verbatim, as the part's last field.
- What the user says about people, senders or their own life is a telling. Never treat
  it as a question to check.
- Never answer and never state facts.
```

- [ ] **Step 9: Write `archie/ask/understand.py`**

```python
"""Understand a message before acting on it (spec: understand-first §2).

One fast-tier call sees the message, the recent conversation and Archie's open questions,
and splits the message into parts: a question, something the user is telling Archie, an
instruction, an answer to one of Archie's questions, or something unclear. Code then
checks the reply: a part's words must be in the message (one part always gets the whole
message), a rewritten question may only use names someone said, and question numbers must
exist. It states no facts, so it needs no citations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Record, Shape

QUESTION_INTENTS = {
    "agenda": "what's on the calendar for a day or range (\"what do I have tomorrow?\", \"what's my week like?\")",
    "brief": "prepare for one specific meeting (\"prep me for 2pm\", \"what's my next meeting about?\")",
    "who": "who someone is, history with them, or a group like \"my family\" (\"who is Priya?\")",
    "loops": "open items: owed, promised, waiting on (\"what do I owe people?\")",
    "next": "what to work on next",
    "ledger": "accomplishments over a period (\"what did I get done this week?\")",
    "handover": "write a project handover",
    "catchup": "what happened while away",
    "help": "what Archie can do or how to use it",
    "search": "anything else: find information in the archive",
}
KINDS = ("question", "tell", "instruct", "answer", "unclear")
FACTS = ("person", "ignore", "unignore", "other")
ACTIONS = ("loop_done", "loop_snooze", "loop_dismiss", "loop_reopen", "meeting_type", "merge_names", "notes",
           "ignore", "unignore", "show_citation", "nudge_snooze", "send", "none")
PARAMS = ("since", "until", "topic", "meeting")

SHAPE = Shape(
    "understand",
    records=(Record("PART", "parts", F("kind", "choice", choices=KINDS), (
        F("text", hint="the part's words, copied exactly from the message"),
        F("resolved", required=False, hint="questions only: the question made to stand alone"),
        F("intent", "choice", required=False, choices=tuple(QUESTION_INTENTS)),
        F("people", "list", required=False, hint="names or emails mentioned"),
        F("since", required=False, hint="ISO date"), F("until", required=False, hint="ISO date"),
        F("topic", required=False), F("meeting", required=False),
        F("fact", "choice", required=False, choices=FACTS),
        F("about", required=False, hint="who or what a telling is about"),
        F("question", "int", required=False, hint="the open question's number"),
        F("action", "choice", required=False, choices=ACTIONS),
        F("target", required=False, hint="which item, in the user's words"),
        F("wanted", required=False, hint="for action none: a short verb phrase"),
        F("options", "int_list", required=False),
        F("ask", required=False, hint="for unclear: one short question back"),
        F("notes", required=False, hint="for notes: the pasted note text verbatim, written last"))),),
    example="PART question\ntext: Do you see the message I sent them?\n"
            "resolved: Do you see the message I sent HeadphonesRUs about the earbud pairing?\n"
            "intent: search\npeople: HeadphonesRUs\ntopic: earbud pairing\n"
            "PART tell\ntext: Sam is my neighbor.\nfact: person\nabout: Sam",
)

_NAMEISH = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[A-Z][\w'-]*")
_PRONOUN_I = {"i", "i'm", "i've", "i'll", "i'd"}


@dataclass
class Part:
    kind: str
    text: str
    resolved: str | None = None
    intent: str | None = None
    params: dict = field(default_factory=dict)
    fact: str | None = None
    about: str | None = None
    question: int | None = None
    action: str | None = None
    target: str | None = None
    wanted: str | None = None
    options: list[int] = field(default_factory=list)
    ask: str | None = None


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def prompt_input(message: str, recent: list[dict], open_qs: list[dict]) -> str:
    out: list[str] = []
    if recent:
        out.append("Recent conversation (oldest first):")
        for e in recent:
            out.append(f"You: {e.get('said', '')}")
            out.append(f"Archie: {_squash(e.get('summary'))[:400]}")
            cites = "; ".join(f"[{c.get('n')}] {c.get('label', '')}" for c in e.get("citations") or [])
            if cites:
                out.append(f"Sources: {cites}")
        out.append("")
    if open_qs:
        out.append("Archie's open questions:")
        out += [f"{i}. {q.get('text', '')}" for i, q in enumerate(open_qs, 1)]
        out.append("")
    out.append(f"Message: {message}")
    return "\n".join(out)


def _grounded(resolved: str, heard: str) -> bool:
    """Every name-like word in the rewrite (capitalized, or an email) was said by someone."""
    return all(w.lower() in heard for w in _NAMEISH.findall(resolved) if w.lower() not in _PRONOUN_I)


def _params(raw: dict) -> dict:
    out = {"people": list(raw.get("people") or [])}
    out.update({k: raw.get(k) for k in PARAMS})
    out["text"] = raw.get("notes")
    return out


def checked(raw: list[dict], message: str, recent: list[dict], open_qs: list[dict]) -> list[Part]:
    said = _squash(message).lower()
    heard = " ".join([said, *(_squash(" ".join([e.get("said", ""), e.get("resolved") or "", e.get("summary", ""),
                                               *(c.get("label", "") for c in e.get("citations") or [])])).lower()
                              for e in recent)])
    parts = []
    for r in raw:
        kind = r.get("kind") if r.get("kind") in KINDS else "question"
        text = (r.get("text") or "").strip()
        if len(raw) == 1 or not text or _squash(text).lower() not in said:
            text = message.strip()
        resolved = r.get("resolved") if kind == "question" else None
        if resolved and not _grounded(resolved, heard):
            resolved = None
        question = r.get("question")
        if kind == "answer" and not (isinstance(question, int) and 1 <= question <= len(open_qs)):
            kind, question = "question", None
        parts.append(Part(kind=kind, text=text, resolved=resolved, intent=r.get("intent"), params=_params(r),
                          fact=r.get("fact"), about=r.get("about"), question=question, action=r.get("action"),
                          target=r.get("target"), wanted=r.get("wanted"), options=list(r.get("options") or []),
                          ask=r.get("ask")))
    return parts or [Part(kind="question", text=message.strip(), intent="search", params=_params({}))]


def understand(ctx: Ctx, message: str, recent: list[dict], open_qs: list[dict]) -> list[Part]:
    local = ctx.now.astimezone()
    system = load_prompt("understand", me_name=ctx.me.name or "the user", now=local.isoformat(timespec="minutes"),
                         weekday=local.strftime("%A"),
                         intents="\n".join(f"- {k}: {v}" for k, v in QUESTION_INTENTS.items()))
    out = ctx.backend.complete(system, prompt_input(message, recent, open_qs), SHAPE, tier="fast")
    return checked(out.get("parts") or [], message, recent, open_qs)
```

- [ ] **Step 10: Run the tests**

Run: `uv run pytest -q tests/unit/test_understand.py tests/unit/test_shapes.py tests/unit/test_shape.py`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add archie/ask/understand.py archie/llm/prompts/understand.md archie/llm/shape.py tests/unit/test_understand.py tests/unit/test_shape.py tests/unit/test_shapes.py
git commit -m "Add the understanding call: split a message into parts, checked by code"
```

---

### Task 3: Switch `ask` to understand-then-dispatch, and rewrite the tests

**Files:**
- Create: `archie/ask/dispatch.py`
- Modify: `archie/ask/pipeline.py` (rewrite `ask`), `archie/ask/router.py` (keep only `QUICK` and `quick_route`), `archie/llm/prompts/route.md` (delete)
- Modify: `tests/support/fixtures.py` (part builders), `tests/support/heuristic_llm.py` (`_understand`)
- Modify (rewrite to the new format): `tests/unit/test_ask.py`, `test_agenda.py`, `test_briefings.py`, `test_cli.py`, `test_correct.py`, `test_ledger.py`, `test_loop_intents.py`, `test_next.py`, `test_notes.py`, `test_remember.py`, `test_tui.py`, `test_who.py`

**Interfaces:**
- Consumes: `understand()`, `Part` (Task 2); `conversation.recent/append`, `citations_of` (Task 1).
- Produces:
  - `dispatch.dispatch(ctx, part: Part, message: str, open_qs: list[dict], last: dict | None = None) -> tuple[str, Answer]` (the label is what handled it, for the usage log)
  - `dispatch.EMPTY` (empty intent params), `CANT_SEND = "I can't send anything; I only read."`, `CANT_YET = "I can't do that yet."`, `UNCLEAR = "I'm not sure what you mean. Could you say it another way?"`
  - `pipeline.Reply(answer: Answer, resolved: str | None, citations: list[dict] | None)` (None = take them from the answer)
  - test helpers in `tests/support/fixtures.py`: `part(kind, **fields) -> dict`, `question(intent, **fields) -> dict`, `understood(*parts) -> dict`
  - usage log entries gain `"parts": [{"kind": str, "handler": str}]`; `"intent"` stays (the first part's handler)

- [ ] **Step 1: Add the test builders to `tests/support/fixtures.py`**

```python
PART_FIELDS = {"text": "", "resolved": None, "intent": None, "people": [], "since": None, "until": None,
               "topic": None, "meeting": None, "fact": None, "about": None, "question": None, "action": None,
               "target": None, "wanted": None, "options": [], "ask": None, "notes": None}


def part(kind: str, **fields) -> dict:
    """One part as the understanding call's parsed reply has it. An empty `text` means the
    whole message (code puts the message there)."""
    unknown = set(fields) - set(PART_FIELDS)
    assert not unknown, f"not a PART field: {unknown}"
    return {"kind": kind, **PART_FIELDS, **fields}


def question(intent: str, **fields) -> dict:
    return part("question", intent=intent, **fields)


def understood(*parts: dict) -> dict:
    return {"parts": list(parts)}
```

- [ ] **Step 2: Rewrite the unit tests to the new format**

In every file below, delete the local router-reply helper, add the builders it needs to the existing `from tests.support.fixtures import …` line, and replace `by_schema(route=` with `by_schema(understand=`. Then make these replacements:

| File | Old | New |
|---|---|---|
| `test_agenda.py` | `route = {"intent": "agenda", … "since": "2026-10-03", "until": "2026-10-05", …}` | `route = understood(question("agenda", since="2026-10-03", until="2026-10-05"))` |
| `test_briefings.py` (`test_brief_intent_end_to_end`) | `route = {"intent": "brief", … "meeting": "next" …}` | `route = understood(question("brief", meeting="next"))` |
| `test_briefings.py` (`test_no_upcoming_meeting`) | `route = {"intent": "brief", … "meeting": None …}` | `route = understood(question("brief"))` |
| `test_cli.py` | `route = {"intent": "search", … "topic": "Priya" …}` | `route = understood(question("search", topic="Priya"))` |
| `test_tui.py` | `route = {"intent": "search", … "topic": "Priya" …}` | `route = understood(question("search", topic="Priya"))` |
| `test_correct.py` | `ROUTE = {"intent": "correct", …}` | `ROUTE = understood(part("instruct", action="meeting_type"))` |
| `test_ledger.py` | `route(since, until)` helper | calls become `understood(question("ledger", since=…, until=…))` with the same dates; `route()` becomes `understood(question("ledger"))` |
| `test_loop_intents.py` | `route("loops")` | `understood(question("loops"))` |
| `test_loop_intents.py` | `route("loop_update")` | `understood(part("instruct", action="loop_done"))` |
| `test_next.py` | `ROUTE = {"intent": "next", …}` | `ROUTE = understood(question("next"))` |
| `test_notes.py` | `route(meeting)` helper | calls become `understood(part("instruct", action="notes", meeting=<same value>, notes=NOTES))` (`None` for `my notes:`, `"design review"`, `"hallway chat"`) |
| `test_remember.py` | `ROUTE = {"intent": "remember", …}` | `ROUTE = understood(part("tell", fact="person"))` |
| `test_remember.py` | `route={"intent": "who", … "topic": "my family" …}` | `understand=understood(question("who", topic="my family"))` |
| `test_who.py` | `route_who(name)` helper | calls become `understood(question("who", people=[<name>]))` |
| `test_who.py` | `== ["route"]` | `== ["understand"]` |
| `test_ask.py` | `route(intent, **params)` helper | `understood(question(intent, **params))` at each call |
| `test_ask.py` | `== ["route"]` | `== ["understand"]` |

In `test_notes.py`, replace the text reply in `test_multi_line_notes_are_saved_whole_and_note_lines_cannot_steer_the_router` with:

```python
    route_text = ("PART instruct\ntext: notes from the design review:\naction: notes\npeople: -\nsince: -\n"
                  "until: -\ntopic: -\nmeeting: design review\n"
                  "notes: Redis approved.\nTopic: hiring plan\nMeeting: hallway chat\n")
```

and rename the test to `test_multi_line_notes_are_saved_whole_and_note_lines_cannot_steer_the_parts`.

In `test_ask.py`, replace `test_text_replies_run_through_the_real_parser_and_verifier`'s `route_text` with:

```python
    route_text = "PART question\ntext: who is priya\nintent: search\ntopic: Priya"
```

Delete `test_also_part_whose_words_are_not_in_the_message_gets_the_whole_message` and `test_part_words_match_despite_collapsed_spaces` (Task 2 covers both rules in `checked`). Replace `test_mixed_message_runs_every_part` with:

```python
def test_mixed_message_runs_every_part(tmp_path):
    from archie.ask.answer import Answer
    from archie.ask.intents import HANDLERS, load_all

    load_all()
    calls = []
    monkey_loop = lambda ctx, q, p: (calls.append(("loop_update", q)), Answer(plain="Marked done: pizzas"))[1]  # noqa
    monkey_rem = lambda ctx, q, p: (calls.append(("remember", q)), Answer(plain="Got it. I'll remember: X"))[1]  # noqa
    saved = dict(HANDLERS)
    HANDLERS.update(loop_update=monkey_loop, remember=monkey_rem)
    try:
        reply = understood(part("instruct", text="I picked up the pizza.", action="loop_done"),
                           part("tell", text="Sam is my neighbor.", fact="person"))
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
        out = render(ask(ctx, "I picked up the pizza. Sam is my neighbor."))
    finally:
        HANDLERS.clear()
        HANDLERS.update(saved)
    assert calls == [("loop_update", "I picked up the pizza."), ("remember", "Sam is my neighbor.")]
    assert "Marked done: pizzas" in out and "Got it. I'll remember: X" in out
```

- [ ] **Step 3: Add the new dispatch and conversation tests to `tests/unit/test_ask.py`**

```python
def test_send_is_refused_plainly_and_nothing_runs(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("instruct", action="send")))))
    assert render(ask(ctx, "email Workpersonthree that the pizza's picked up")) == "I can't send anything; I only read."


def test_an_instruction_with_no_action_says_it_cannot_yet(tmp_path):
    reply = understood(part("instruct", action="none", wanted="filter Today by day"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, "only show work stuff on weekdays")) == "I can't do that yet."


def test_unclear_asks_back_with_a_short_question_only(tmp_path):
    reply = understood(part("unclear", ask="Which one: Workpersonthree's pizza or Workpersonfour's form?"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, "she's done with it")) == "Which one: Workpersonthree's pizza or Workpersonfour's form?"
    ctx.backend = FakeBackend(by_schema(understand=understood(part("unclear", ask="Workpersonthree is done."))))
    assert render(ask(ctx, "she's done with it")) == "I'm not sure what you mean. Could you say it another way?"


def test_answer_to_who_is_reaches_remember_with_the_address(tmp_path):
    from archie.ask.answer import Answer
    from archie.ask.intents import HANDLERS, load_all
    from archie.derive.dedupe import save_questions

    load_all()
    seen = []
    saved = dict(HANDLERS)
    HANDLERS["remember"] = lambda ctx, q, p: (seen.append(q), Answer(plain="Got it."))[1]
    try:
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("answer", question=1)))))
        save_questions(ctx.home, [{"id": "q1", "kind": "who_is", "person": "x", "status": "open",
                                   "text": "Who is a@b.co? Tell me, e.g. \"a@b.co is my plumber\".",
                                   "asked_at": "2026-10-01T00:00:00+00:00"}])
        ask(ctx, "it's my plumber")
    finally:
        HANDLERS.clear()
        HANDLERS.update(saved)
    assert seen == ["a@b.co: it's my plumber"]


def test_each_exchange_is_remembered_with_its_numbered_sources(tmp_path):
    import json

    synth = {"summary": [{"text": "Priya is the PM for auth.", "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}],
             "sections": []}
    reply = understood(question("search", topic="Priya", resolved="Who is Priya?"))
    ctx = seeded(tmp_path, by_schema(understand=reply, answer=synth))
    ask(ctx, "who is priya")
    [entry] = [json.loads(x) for x in (ctx.home / "state/conversation.jsonl").read_text().splitlines()]
    assert entry["said"] == "who is priya" and entry["resolved"] == "Who is Priya?"
    assert entry["citations"][0]["file"] == "people/priya_sharma.md" and entry["citations"][0]["n"] == 1
    assert entry["summary"].startswith("Priya is the PM for auth. [1]")
    log = [json.loads(x) for x in (ctx.home / "logs/usage.jsonl").read_text().splitlines()]
    assert log[0]["parts"] == [{"kind": "question", "handler": "search"}]
```

- [ ] **Step 4: Update `HeuristicLLM` in `tests/support/heuristic_llm.py`**

Rename `_route` to `_classify` (it's a helper now, not a shape), update the module docstring's first bullet to `- understand: keyword rules, one part per message.`, and add:

```python
    TO_PART = {"loop_update": ("instruct", "loop_done"), "correct": ("instruct", "meeting_type"),
               "notes": ("instruct", "notes")}

    def _understand(self, system, user):
        msg = user.rsplit("Message:", 1)[-1].strip()
        r = self._classify(system, msg)
        p = r["params"]
        item = {"kind": "question", "text": msg, "resolved": None, "intent": r["intent"], "people": p["people"],
                "since": p["since"], "until": p["until"], "topic": p["topic"], "meeting": p["meeting"],
                "notes": p["text"], "fact": None, "about": None, "question": None, "action": None, "target": None,
                "wanted": None, "options": [], "ask": None}
        if r["intent"] in self.TO_PART:
            item["kind"], item["action"] = self.TO_PART[r["intent"]]
            item["intent"] = None
        return {"parts": [item]}
```

- [ ] **Step 5: Run the rewritten tests to see them fail**

Run: `uv run pytest -q tests/unit tests/vignettes`
Expected: many FAIL, because `ask()` still calls the old router (shape `route`, no `understand` handler) and `dispatch` doesn't exist.

- [ ] **Step 6: Write `archie/ask/dispatch.py`**

```python
"""Send each understood part where it belongs (spec: understand-first §2.2).

Until the told record (step 2) and the action list (step 3) exist, tellings go to
`remember` and instructions go to the intents that already carry them out."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import HANDLERS
from archie.ask.understand import Part
from archie.derive.audit import YES_NO

EMPTY = {"people": [], "since": None, "until": None, "topic": None, "meeting": None, "text": None}
CANT_SEND = "I can't send anything; I only read."
CANT_YET = "I can't do that yet."
UNCLEAR = "I'm not sure what you mean. Could you say it another way?"
ACTION_INTENT = {"loop_done": "loop_update", "loop_snooze": "loop_update", "loop_dismiss": "loop_update",
                 "loop_reopen": "loop_update", "meeting_type": "correct", "merge_names": "correct", "notes": "notes"}


def _who_is_subject(q: dict) -> str:
    m = re.match(r"Who is (.+?)\?", q.get("text", ""))
    return m.group(1) if m else ""


def dispatch(ctx: Ctx, part: Part, message: str, open_qs: list[dict], last: dict | None = None) -> tuple[str, Answer]:
    """(what handled the part, for the usage log; the reply)."""
    if part.kind == "question":
        name = part.intent if part.intent in HANDLERS else "search"
        label = name if name == part.intent else f"{part.intent}->search"
        return label, HANDLERS[name](ctx, part.resolved or part.text, {**EMPTY, **part.params})
    if part.kind == "tell":
        return "remember", HANDLERS["remember"](ctx, part.text, dict(EMPTY))
    if part.kind == "answer":
        q = open_qs[part.question - 1]
        if q.get("kind") in YES_NO:
            return "clarify", HANDLERS["clarify"](ctx, part.text, dict(EMPTY))
        subject = _who_is_subject(q)
        return "remember", HANDLERS["remember"](ctx, f"{subject}: {part.text}" if subject else part.text, dict(EMPTY))
    if part.kind == "instruct":
        name = ACTION_INTENT.get(part.action or "")
        if name == "notes":  # the notes handler finds the note's start in the whole message
            return "notes", HANDLERS["notes"](ctx, message, {**EMPTY, **part.params})
        if name:
            return name, HANDLERS[name](ctx, part.text, dict(EMPTY))
        if part.action == "send":
            return "send", Answer(plain=CANT_SEND)
        return f"{part.action or 'none'}->cant", Answer(plain=CANT_YET)
    ask = (part.ask or "").strip()
    return "unclear", Answer(plain=ask if ask.endswith("?") and len(ask) <= 160 else UNCLEAR)
```

- [ ] **Step 7: Rewrite `archie/ask/pipeline.py`**

```python
"""ask(): the single entry point behind `archie ask` and the TUI's Ask pane.

A message is first understood (understand.py) with the recent conversation and Archie's
open questions in view, then each part is sent where it belongs (dispatch.py). Every
finished exchange goes to state/conversation.jsonl, which follow-ups read, and to
logs/usage.jsonl (local only, gitignored): what was said, how each part was handled, how
long it took, whether anything was found, and the answer shown (with source paths), so
answers can be triaged later."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import NamedTuple

from archie.ask import conversation
from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.dispatch import EMPTY, dispatch
from archie.ask.intents import HANDLERS, load_all
from archie.ask.router import quick_route
from archie.ask.understand import understand


class Reply(NamedTuple):
    answer: Answer
    resolved: str | None
    citations: list[dict] | None  # None: take them from the answer


def _log(ctx: Ctx, entry: dict) -> None:
    try:
        path = ctx.home / "logs/usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break an answer


def combine(first: Answer, more: list[Answer]) -> Answer:
    """One reply for a mixed message: plain replies are joined; otherwise they become notes."""
    from archie.ask.render import render

    texts = [render(a) for a in more]
    if first.plain is not None:
        first.plain = "\n\n".join([first.plain, *texts])
    else:
        first.notes += texts
    return first


def _respond(ctx: Ctx, question: str, entry: dict) -> Reply:
    from archie.ask.intents.clarify import looks_like_answer
    from archie.derive.audit import YES_NO
    from archie.derive.dedupe import open_questions

    quick = quick_route(question)
    if quick:
        entry.update(quick=True, intent=quick)
        return Reply(HANDLERS[quick](ctx, question, dict(EMPTY)), None, None)
    open_qs = open_questions(ctx.home)
    if any(q["kind"] in YES_NO for q in open_qs) and looks_like_answer(question):
        entry["intent"] = "clarify"
        return Reply(HANDLERS["clarify"](ctx, question, dict(EMPTY)), None, None)
    recent = conversation.recent(ctx.home, ctx.now)
    parts = understand(ctx, question, recent, open_qs)
    last = recent[-1] if recent else None
    handled = [dispatch(ctx, p, question, open_qs, last) for p in parts]
    entry["intent"] = handled[0][0]
    entry["parts"] = [{"kind": p.kind, "handler": label} for p, (label, _) in zip(parts, handled)]
    resolved = next((p.resolved for p in parts if p.kind == "question" and p.resolved), None)
    return Reply(combine(handled[0][1], [a for _, a in handled[1:]]), resolved, None)


def ask(ctx: Ctx, question: str) -> Answer:
    from archie.ask.render import citations_of, render
    from archie.derive.audit import resolve_answered

    load_all()
    started = time.monotonic()
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question, "quick": False}
    try:
        reply = _respond(ctx, question, entry)
        answer = reply.answer
        resolve_answered(ctx)  # e.g. closing an item clears "still needed?" about it
        entry.update(nothing_found=answer.nothing_found, dropped=answer.dropped,
                     claims=len(answer.summary) + sum(len(s.items) for s in answer.sections),
                     answer=render(answer, sources=True, paths=True)[:6000])
        conversation.append(ctx.home, {
            "ts": ctx.now.isoformat(), "said": question, "resolved": reply.resolved,
            "summary": render(answer)[:800],
            "citations": citations_of(answer) if reply.citations is None else reply.citations})
        return answer
    except Exception as exc:
        entry["error"] = str(exc)[:200]
        raise
    finally:
        entry["ms"] = int((time.monotonic() - started) * 1000)
        _log(ctx, entry)
```

- [ ] **Step 8: Cut `archie/ask/router.py` down to the quick routes**

Replace the whole file with:

```python
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
```

Delete `archie/llm/prompts/route.md` (`git rm archie/llm/prompts/route.md`).

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest -q`
Expected: all pass (the 4 existing strict xfails stay xfail). If a test still names the shape `route` or imports `route_all`, `split_parts`, `INTENT_HELP` or `router.SHAPE`, rewrite it to the new format as in Step 2.

- [ ] **Step 10: Commit**

```bash
git add -A archie/ask archie/llm/prompts tests
git commit -m "ask: understand each message into parts, then dispatch; tests use the new format"
```

---

### Task 4: Follow-ups ("show N", "really?") and vignette O

**Files:**
- Create: `archie/ask/followup.py`, `tests/unit/test_followup.py`, `tests/vignettes/test_o_followups.py`
- Modify: `archie/ask/pipeline.py` (`_respond` shortcuts), `archie/ask/dispatch.py` (`show_citation`)

**Interfaces:**
- Consumes: `Reply`, `_respond` (Task 3), entries from `conversation.recent` (Task 1), `citations_of` (Task 1), `ctx.index.chunk_text(path, chunk_id) -> str | None` (existing).
- Produces:
  - `followup.citation_number(text: str) -> int | None`
  - `followup.is_recheck(text: str) -> bool`
  - `followup.show(ctx, last: dict | None, n: int) -> Answer`
  - `followup.recheck(previous: dict, answer: Answer, new_citations: list[dict]) -> Answer`
  - `followup.CHECKED = "I checked again."`, `followup.CHANGED = "This is different from my earlier answer."`

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_followup.py
from archie.ask.answer import Answer
from archie.ask.followup import citation_number, is_recheck, recheck, show
from archie.ask.render import render
from tests.support.fixtures import make_ctx

LAST = {"said": "q", "resolved": None, "summary": "s",
        "citations": [{"n": 1, "file": "people/a.md", "chunk": "c0", "label": "A (dossier)", "quote": "alpha beta gamma"},
                      {"n": 2, "file": "people/b.md", "chunk": "c0", "label": "B (dossier)", "quote": "delta epsilon"}]}


def test_citation_number():
    assert [citation_number(t) for t in ("show 1", "Show [2]", "open source 3", "show me citation 4.", "show me")] == \
        [1, 2, 3, 4, None]


def test_is_recheck():
    assert all(is_recheck(t) for t in ("really?", "Really", "are you sure?", "is that right?", "double-check that"))
    assert not is_recheck("really, who is Priya?")


def test_show_missing_citation_says_what_exists(tmp_path):
    ctx = make_ctx(tmp_path)
    assert render(show(ctx, LAST, 3)) == "The last answer has citations 1–2."
    assert render(show(ctx, {"citations": []}, 1)) == "There's no recent answer with sources to show."
    assert render(show(ctx, None, 1)) == "There's no recent answer with sources to show."


def test_show_leads_with_the_label_and_ends_with_the_path(tmp_path):
    ctx = make_ctx(tmp_path)
    lines = render(show(ctx, LAST, 2)).splitlines()
    assert lines[0] == "[2] B (dossier)" and lines[1] == "“delta epsilon”" and lines[-1] == "people/b.md"


def test_recheck_says_when_the_answer_changed():
    same = recheck(LAST, Answer(plain="x"), [{"file": "people/a.md"}])
    assert render(same) == "I checked again.\nx"
    changed = recheck(LAST, Answer(nothing_found=True), [])
    assert render(changed).startswith("I checked again. This is different from my earlier answer.\n")
```

- [ ] **Step 2: Write the failing vignette test**

```python
# tests/vignettes/test_o_followups.py
"""Vignette O (docs/VIGNETTES.md): follow-ups."""

from datetime import timedelta

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write
from tests.support.fixtures import NOW, make_ctx, question, understood

DOSSIER = ("---\nname: HeadphonesRUs\n---\n## My notes\n"
           "You wrote to HeadphonesRUs on Oct 2: one earbud pairs and the other stays red.\n"
           "HeadphonesRUs replied Oct 3, offering a replacement right earbud for $49.\n")
FOLLOW_UP = "Do you see the message I sent HeadphonesRUs about the earbud pairing?"


def model(system, user, shape, tier):
    if shape.name == "understand":
        msg = user.rsplit("Message:", 1)[-1].strip()
        if msg.startswith("do you see"):
            return understood(question("search", resolved=FOLLOW_UP, people=["HeadphonesRUs"], topic="earbud pairing"))
        return understood(question("search", topic="HeadphonesRUs earbud"))
    return {"summary": [{"text": "HeadphonesRUs offered a replacement right earbud.",
                         "citations": [{"ref": 1, "quote": "offering a replacement right earbud for $49"}]}],
            "sections": []}


def test_O_follow_ups(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    atomic_write(ctx.home / "people/status_audio.md", DOSSIER)
    ctx.index.sync()

    first = render(ask(ctx, "did Status reply about my earbud?"))
    assert "[1]" in first

    ctx.now = NOW + timedelta(minutes=2)
    ask(ctx, "do you see the message I sent them?")
    seen = fb.calls[-2]["user"]  # the understanding call for the follow-up
    assert "You: did Status reply about my earbud?" in seen and "Archie: HeadphonesRUs offered" in seen
    assert f"Question: {FOLLOW_UP}" in fb.calls[-1]["user"]  # the answer was written for the resolved question

    ctx.now = NOW + timedelta(minutes=3)
    calls = len(fb.calls)
    shown = render(ask(ctx, "show 1"))
    assert len(fb.calls) == calls  # no model call
    assert shown.startswith("[1] ") and "offering a replacement right earbud for $49" in shown
    assert shown.splitlines()[-1] == "people/status_audio.md"

    ctx.now = NOW + timedelta(minutes=4)
    again = render(ask(ctx, "really?"))
    assert again.startswith("I checked again.")
    assert "This is different" not in again
    assert f"Question: {FOLLOW_UP}" in fb.calls[-1]["user"]  # the same question, asked again

    ctx.now = NOW + timedelta(minutes=45)
    ask(ctx, "do you see the message I sent them?")
    assert "Recent conversation" not in fb.calls[-2]["user"]  # after a quiet half hour, a fresh start


def test_O_really_with_nothing_recent_is_an_ordinary_message(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    render(ask(ctx, "really?"))
    assert fb.calls[0]["shape"].name == "understand"
    ctx.now = NOW + timedelta(minutes=1)
    render(ask(ctx, "really?"))  # the last exchange was itself "really?": no endless re-asking
    assert fb.calls[-1]["shape"].name in ("understand", "answer")
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest -q tests/unit/test_followup.py tests/vignettes/test_o_followups.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'archie.ask.followup'`.

- [ ] **Step 4: Write `archie/ask/followup.py`**

```python
"""Follow-ups that need no model call (spec: understand-first §2.4): "show 2" opens a
citation from the last answer, and "really?" asks the last question again."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.render import NOTHING

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


def _around(text: str, quote: str, width: int = 200) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    q = re.sub(r"\s+", " ", quote or "").strip().lower()
    at = flat.lower().find(q[:40]) if q else -1
    if at < 0:
        return flat[: 2 * width]
    start, end = max(0, at - width), min(len(flat), at + len(q) + width)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


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
    return Answer(plain="\n".join(lines))


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
```

- [ ] **Step 5: Add the shortcuts to `_respond` in `archie/ask/pipeline.py`**

Add `from archie.ask.followup import citation_number, is_recheck, recheck, show` to the imports, and insert right after the `quick_route` block (before `open_qs = …`):

```python
    recent = conversation.recent(ctx.home, ctx.now)
    last = recent[-1] if recent else None
    n = citation_number(question)
    if n is not None:
        entry.update(quick=True, intent="show_citation")
        return Reply(show(ctx, last, n), (last or {}).get("resolved"), (last or {}).get("citations") or [])
    again = (last or {}).get("resolved") or (last or {}).get("said")
    if is_recheck(question) and again and not is_recheck(again):
        entry["recheck"] = again
        reply = _respond(ctx, again, entry)
        from archie.ask.render import citations_of

        new = citations_of(reply.answer)
        return Reply(recheck(last, reply.answer, new), again, new)
```

Then remove the now-duplicate `recent = …` and `last = …` lines further down in `_respond`.

- [ ] **Step 6: Handle `show_citation` in `archie/ask/dispatch.py`**

Add `from archie.ask.followup import citation_number, show` to the imports and, inside the `instruct` branch before `name = ACTION_INTENT.get(...)`:

```python
        if part.action == "show_citation":
            m = re.search(r"\d+", part.text)
            n = citation_number(part.text) or (int(m.group()) if m else 1)
            return "show_citation", show(ctx, last, n)
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest -q tests/unit/test_followup.py tests/vignettes/test_o_followups.py && uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add archie/ask/followup.py archie/ask/pipeline.py archie/ask/dispatch.py tests/unit/test_followup.py tests/vignettes/test_o_followups.py
git commit -m "Follow-ups: show a citation from the last answer, re-check with \"really?\" (vignette O)"
```

---

### Task 5: Docs, OKF and a live check

**Files:**
- Modify: `docs/DESIGN.md` (§4 storage layout, §8), `docs/VIGNETTES.md` (row O), `docs/superpowers/specs/2026-10-03-understand-first-design.md` (§2.4 "really?" is a code shortcut), `okf/components/ask.md`, `okf/log.md`

- [ ] **Step 1: `docs/DESIGN.md` §4** — add under `state/`:

```
│   ├── cursors.yaml         # per-source sync cursors (tracked in git)
│   └── conversation.jsonl   # recent ask exchanges, for follow-ups (last 200)
```

- [ ] **Step 2: `docs/DESIGN.md` §8** — replace step 1 of the pipeline ("**Route:** …") with:

```markdown
1. **Understand:** one fast-tier call reads the message with the last few exchanges
   (`state/conversation.jsonl`, up to 3, ended by 30 quiet minutes) and Archie's open
   questions, and splits it into parts: a question (with its intent and parameters, and
   "them"/"that" filled in), something the user is telling Archie, an instruction, an
   answer to an open question, or something unclear. Code checks the reply: a part's words
   must be in the message, a rewritten question may only use names someone said, and
   question numbers must exist. It states no facts, so it needs no citations. Code-only
   shortcuts come first: the quick questions, "show N" (a citation from the last answer),
   "really?" (the last question again), and a plain yes or no to one open question.
```

In the intents table, delete the `remember`, `loop_update`, `correct`, `clarify` and `notes` rows and add, after the table:

```markdown
Tellings, instructions and answers are not intents. Until build steps 2–3 of the
understand-first spec land, tellings and answers to "Who is …?" use the `remember` code,
yes/no answers use `clarify`, and instructions use `loop_update` (done, snooze, dismiss,
reopen), `correct` (meeting type, merging names) and `notes`. Sending anything gets "I
can't send anything; I only read."
```

- [ ] **Step 3: `docs/VIGNETTES.md`** — set row O's Status to `✅`.

- [ ] **Step 4: the spec, §2.4** — replace the "really?" bullet with:

```markdown
- **"really?" / "are you sure?"** is recognized by code (no extra model call to classify
  it). The previous question is asked again in full, and the reply opens with "I checked
  again." If the sources behind the answer changed completely, or one answer found
  something and the other didn't, it adds "This is different from my earlier answer."
```

- [ ] **Step 5: `okf/components/ask.md`** — change the description to `The one user entry point. It understands each message (with the recent conversation and open questions) into parts, sends each part where it belongs, retrieves a context packet for questions, has the LLM write an answer, verifies the citations, and renders readable output.` Replace the `pipeline.py` and `router.py` bullets with:

```markdown
- `pipeline.py`: `ask(ctx, question) -> Answer`. Code-only shortcuts first (quick questions, "show N", "really?", a plain yes/no to one open question), then `understand`, then `dispatch` for every part; replies from a mixed message are `combine`d. Each exchange is appended to `state/conversation.jsonl` (see `conversation.py`) and to `logs/usage.jsonl` (local and gitignored) with the handler of each part, whether a shortcut was used, ms, nothing_found, dropped claims, the answer as shown and any error.
- `understand.py`: one fast-tier call (`understand` shape, `PART` records) splits the message into question, tell, instruct, answer and unclear parts. `checked` enforces: a part's words must be in the message (a single part always gets the whole message), a rewritten question (`resolved`) may only use name-like words someone said, and an answer must point at a real open question. `QUESTION_INTENTS` lists the intents a question can have.
- `dispatch.py`: questions go to their intent (unknown ones to `search`, on the rewritten question when there is one). Until build steps 2–3: tellings and "Who is …?" answers go to `remember`, yes/no answers to `clarify`, instructions to `loop_update`, `correct` or `notes`; `send` gets "I can't send anything; I only read." and anything else "I can't do that yet."; unclear parts ask back.
- `conversation.py`: the last 200 exchanges (`said`, `resolved`, `summary`, numbered `citations`). `recent` returns up to 3, oldest first, ended by a 30-minute gap.
- `followup.py`: "show N" prints citation N of the last answer (label, quote, the text around it, then the path) with no model call; "really?" re-asks the last question and says when the answer changed.
- `router.py`: `quick_route` handles unambiguous, parameter-free questions in code ("what's next?", "what do I owe people?", "help") and skips the model call.
```

- [ ] **Step 6: `okf/log.md`** — add at the top of `## 2026-10-03`:

```markdown
- M5 step 1 built: `ask` now understands each message into parts with the recent conversation (`state/conversation.jsonl`) and open questions in view, replacing the menu router (`archie/ask/understand.py`, `dispatch.py`, `conversation.py`, `followup.py`). "show N" and "really?" work without a model call. Vignette O passes. Tests now hand the fake model the new `PART` format directly.
```

- [ ] **Step 7: Run the checks**

Run: `uv run pytest -q && uv run python scripts/okf_check.py`
Expected: all pass; OKF check exits 0.

- [ ] **Step 8: Live check with Gemini** (costs about 1¢ per message)

Run each, a minute or two apart:

```bash
uv run archie ask "did Status reply about my earbud?"
uv run archie ask "do you see the message I sent them?"
uv run archie ask "show 1"
uv run archie ask "really?"
uv run archie ask "ftbrmktf@sxziiqsov.us is spam"
```

Expected: the second answer is about the user's own message to HeadphonesRUs; "show 1" prints a source with no model call; "really?" opens with "I checked again."; the spam message is routed as a telling (it reaches `remember` until step 2, which is expected). Then check the cost:

```bash
tail -12 ~/.archie/logs/llm_usage.jsonl
tail -5 ~/.archie/logs/usage.jsonl
```

Expected: about 0.1¢ more per message than before for the understanding call. Note anything surprising in `okf/log.md`.

- [ ] **Step 9: Commit**

```bash
git add docs okf
git commit -m "Docs for understand-first step 1: DESIGN §4/§8, vignette O, OKF ask component"
```

# Fixes That Last — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop whole classes of review findings from recurring. Names match the same way everywhere (possessives included), and `who` falls back to search instead of giving up. The usage log shows what Archie understood and read. One evidence selector serves people files, `who` and briefings. Derivations re-run when their logic changes, and old person tellings are replayed. Signatures become quotable chunks, so titles come from code. Reviews turn failures into tests.

**Architecture:** A new top-level `archie/names.py` normalizer is used by the understanding call's grounding check and by `PeopleDirectory`. `archie/ask/evidence.py` is the one way to pick a person's chunks. `archie/derive/versions.py` stamps derivations; `archie/derive/replay.py` replays tellings as a post-index step whose sentences reach the sync report. The gmail chunker emits signature chunks `s{i}`, and `archie/derive/titles.py` reads titles from them at question time.

**Tech Stack:** Python 3.11+, pytest, SQLite FTS5 + sqlite-vec, `FakeBackend`, `HeuristicLLM` (vignettes).

**Spec:** `docs/superpowers/specs/2026-10-04-durable-fixes-design.md` (build order in its "Build order" section; this plan follows it).

## Global Constraints

- Files under `~/.archie/` are the source of truth; SQLite is a rebuildable index. No fact only in the DB. `journal/told.md` is never rewritten by replays.
- In derived Markdown, Archie writes only inside `<!-- archie:auto -->` fences.
- Model claims carry `{file, chunk, quote}`; the verifier drops anything not verbatim in the cited chunk. Counts, dates and signature titles come from code.
- The user's own words are never checked against the archive.
- Read-only toward the world; no new commands; maintenance only under `archie admin`.
- Answers open with a plain-English summary; IDs and paths never lead.
- Fallback lines are written by code, exactly: "I didn't recognise anyone called {name}, so I searched everything instead." / "I couldn't tell who you meant, so I searched everything instead." / "I didn't recognise anyone called {name}, and a search found nothing about it." (with no name: "I couldn't tell who you meant, and a search found nothing about it.")
- Replay scope: only told lines whose result is `saved only` or starts with `remembered:`. Never ignore/un-ignore lines, never anything that could close an item. Loops are never replayed.
- `people.facts_max_chars` default 40,000. `CHUNKER_VERSION` becomes `"3"`.
- Before every commit (CLAUDE.md): update the OKF bundle for what the task touched (`okf/components/*.md`, `okf/log.md` for design/structure changes), and the pre-commit hook (`scripts/okf_check.py`, `graphify update .`) must pass. Never bypass it. Don't stage unrelated working-tree changes.
- Run the suite with `uv run pytest -q` (full) or `uv run pytest tests/unit/test_x.py -q` (focused).

## Review Focus

- A name that naturally ends in "s" ("James", "Chris", "Wes") must still match exactly, and the extra stripped form must never create or pick a different person. → Task 1.
- A signature with no title (only name and phone, "Sent from my iPhone", "Thanks!", a quote line) must give no "Role:" line, not a junk one. → Task 10.
- A hand-edited `journal/told.md` (a reworded result, a deleted or malformed line, a blank file) must not crash replay; unparseable lines are skipped. → Task 7.
- A person with no email identifiers (someone the user only told Archie about, like Acorn) gets an empty evidence list and no titles, and `who` still answers from their notes. → Task 4.
- A model failure or budget stop part-way through a rebuild or replay must leave nothing half-written: no partial fact list, and no version recorded for an unapplied telling. → Tasks 6 and 7.

---

## Step 1 — Names (spec §4)

### Task 1: Shared name normalizer, used for grounding and lookup

**Files:**
- Create: `archie/names.py`
- Create: `okf/components/names.md`
- Modify: `archie/ask/understand.py` (`_words`, around line 145)
- Modify: `archie/derive/people.py` (`find`, around line 116; `mentioned_in` / `_named`, lines 132–162)
- Test: `tests/unit/test_names.py` (new), `tests/unit/test_understand.py`, `tests/unit/test_people.py`

**Interfaces:**
- Produces: `name_key(word: str) -> str`; `name_forms(word: str) -> set[str]`; `PeopleDirectory._named(name: str, text: str, any_case: bool = False) -> bool`; `PeopleDirectory.mentioned_in(text: str, any_case: bool = False) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_names.py`:

```python
from archie.names import name_forms, name_key


def test_name_key_drops_possessives_and_edge_punctuation():
    assert name_key("Workperson's") == "workperson"
    assert name_key("Workperson’s") == "workperson"
    assert name_key("Wes'") == "wes"
    assert name_key("(Priya)") == "priya"
    assert name_key("Workpersons") == "workpersons"  # no apostrophe: the key keeps the s


def test_name_forms_adds_the_s_less_form():
    assert name_forms("Workpersons") == {"workpersons", "workperson"}
    assert name_forms("Workperson's") == {"workperson's", "workperson"}
    assert "james" in name_forms("James") and "jame" in name_forms("James")  # only widens what was heard
    assert name_forms("Ross") >= {"ross"}
    assert name_forms("is") == {"is"}  # short words get no extra form
```

Append to `tests/unit/test_understand.py`:

```python
def test_possessive_names_stay_grounded():
    raw = [{"kind": "question", "text": "x", "intent": "who", "people": ["Workperson"], "topic": "title"}]
    for message in ("What is Workpersons title?", "What is Workperson's title?", "What is Workperson’s title?"):
        [p] = checked(raw, message, [], [])
        assert p.params["people"] == ["Workperson"], message


def test_names_nobody_said_are_still_dropped():
    raw = [{"kind": "question", "text": "x", "intent": "who", "people": ["Bose"]}]
    [p] = checked(raw, "What is Workpersons title?", [], [])
    assert p.params["people"] == []
```

Append to `tests/unit/test_people.py` (follow the file's existing way of building a `PeopleDirectory`; if it has none, build one from notes written with `write_note` and `PeopleDirectory.load(ctx.home)` as in `tests/unit/test_who.py::seed`):

```python
def test_find_and_mentioned_in_accept_possessives(tmp_path):
    from archie.derive.people import PeopleDirectory
    from archie.store.files import Note, write_note
    from tests.support.fixtures import make_ctx

    ctx = make_ctx(tmp_path)
    for eid, name, aliases in (("workperson_acorn", "Workperson Acorn", ["workperson@ow.example"]),
                               ("james_lee", "James Lee", ["james@x.example"]),
                               ("acorn", "Acorn", [])):
        write_note(ctx.home / f"people/{eid}.md",
                   Note(meta={"entity_id": eid, "name": name, "aliases": aliases}, body="## My notes\n"))
    d = PeopleDirectory.load(ctx.home)
    assert d.find("Workperson's") == ["workperson_acorn"]
    assert d.find("Workpersons") == ["workperson_acorn"]
    assert d.find("James") == ["james_lee"]  # a name ending in s still matches exactly
    assert d.find("Jame") == []
    assert d.mentioned_in("Can you ship Workpersons laptop?") == ["workperson_acorn"]
    assert d.mentioned_in("Workperson's laptop") == ["workperson_acorn"]
    assert "acorn" not in d.mentioned_in("Workperson Acorn's laptop")  # Acorn inside a longer name still isn't Acorn
    assert d.mentioned_in("tell me about workperson") == []  # one-word names still need a capital
    assert d.mentioned_in("tell me about workperson", any_case=True) == ["workperson_acorn"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_names.py tests/unit/test_understand.py tests/unit/test_people.py -q`
Expected: FAIL (`ModuleNotFoundError: archie.names`; the possessive cases fail).

- [ ] **Step 3: Implement**

`archie/names.py`:

```python
"""One way to compare names (spec: durable-fixes §4): case, curly quotes, edge punctuation
and possessives ("Workperson's", "Workpersons") don't stop a name from matching."""

from __future__ import annotations

_QUOTES = str.maketrans({"’": "'", "‘": "'"})
_EDGE = ".,;:!?\"()[]{}-"


def name_key(word: str) -> str:
    w = word.translate(_QUOTES).lower().strip(_EDGE)
    if w.endswith("'s"):
        w = w[:-2]
    elif w.endswith("'"):
        w = w[:-1]
    return w.strip(_EDGE + "'")


def name_forms(word: str) -> set[str]:
    """The word as heard, its key, and the key without a trailing s ("workpersons" -> "workperson")."""
    key = name_key(word)
    forms = {word.translate(_QUOTES).lower().strip(".'-"), key}
    if key.endswith("s") and len(key) > 3:
        forms.add(key[:-1])
    return {f for f in forms if f}
```

`archie/ask/understand.py`, replace `_words`:

```python
def _words(text: str) -> set[str]:
    from archie.names import name_forms

    return {f for w in _WORD.findall(text or "") for f in name_forms(w)}
```

`archie/derive/people.py`, at the end of `find` replace `return exact or first` with:

```python
        if exact or first:
            return exact or first
        from archie.names import name_forms

        for form in sorted(name_forms(query), key=len, reverse=True):  # "workperson's" / "workpersons" -> "workperson"
            if form != q:
                hits = self.find(form)
                if hits:
                    return hits
        return []
```

(Guard against recursion: `name_forms` of a form never yields a longer string, and `form != q` stops self-calls. Recursion ends because each call's query is shorter or equal and equal is skipped.)

In `mentioned_in`, add the `any_case` parameter, pass it to `_named`, and allow a possessive after the name in both the blanking regex and `_named`:

```python
_POSS = r"(?:['’]s|s['’]?)?"

    def mentioned_in(self, text: str, any_case: bool = False) -> list[str]:
        """Entity ids whose name, a name alias, or a first name (3+ letters) appears in text,
        possessives included ("Workperson's", "Workpersons").

        A name inside another person's longer name doesn't count ("Acorn" in "Workperson Acorn" is
        not Acorn). A one-word name must be capitalized ("a acorn" is nobody) unless any_case."""
        full: list[tuple[str, str]] = []  # (multi-word name, entity id), longest first
        for eid, meta in self.meta.items():
            for n in [meta.get("name"), *(meta.get("aliases") or [])]:
                if n and "@" not in str(n) and " " in str(n).strip():
                    full.append((str(n).strip(), eid))
        full.sort(key=lambda x: -len(x[0]))
        out = []
        for eid, meta in self.meta.items():
            names = {str(n) for n in [meta.get("name"), *(meta.get("aliases") or [])] if n and "@" not in str(n)}
            first = str(meta.get("name") or "").split(" ")[0]
            if first and len(first) > 2:
                names.add(first)
            seen = text
            for other, owner in full:  # blank out other people's longer names that contain ours
                if owner != eid and any(re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", other.lower())
                                        for n in names):
                    seen = re.sub(rf"(?<!\w){re.escape(other)}{_POSS}(?!\w)", " ", seen, flags=re.IGNORECASE)
            if any(self._named(n, seen, any_case) for n in names):
                out.append(eid)
        return out

    @staticmethod
    def _named(name: str, text: str, any_case: bool = False) -> bool:
        if " " in name.strip() or any_case:
            return bool(re.search(rf"(?<!\w){re.escape(name)}{_POSS}(?!\w)", text, re.IGNORECASE))
        return bool(re.search(rf"(?<!\w){re.escape(name[:1].upper() + name[1:])}{_POSS}(?!\w)", text))
```

Put `_POSS` at module level next to `EMAIL`. The `{_POSS}` after `re.escape(other)` in the blanking `re.sub` makes "Workperson Acorn's" blank out as a whole.

`okf/components/names.md`:

```markdown
---
type: Component
title: Name matching
description: One way to compare names everywhere (case, curly quotes, edge punctuation, possessives like "Workperson's" and "Workpersons").
resource: archie/names.py
status: active
tags: [component]
---

- `name_key` lowercases, straightens quotes and drops a trailing `'s` / `'`; `name_forms` adds the form without a trailing s ("workpersons" → "workperson"). The extra forms only widen what counts as said; they never add a name.
- Used by the understanding call's grounding check ([ask](ask.md)) and by `PeopleDirectory.find` / `mentioned_in` ([derivers](derivers.md)).
- Why: "What is Workpersons title?" lost Workperson because grounding needed "workperson" as a whole word (review 2026-10-04).
```

Add a link to `names.md` in `okf/components/index.md` in the same style as the other entries.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_names.py tests/unit/test_understand.py tests/unit/test_people.py -q`, then `uv run pytest -q`
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
git add archie/names.py archie/ask/understand.py archie/derive/people.py okf/components/names.md okf/components/index.md tests/unit/test_names.py tests/unit/test_understand.py tests/unit/test_people.py
git commit -m "Names match with possessives: one normalizer for grounding and people lookup"
```

### Task 2: Code finds known people; `who` falls back to search

**Files:**
- Modify: `archie/derive/people.py` (add `names_in`)
- Modify: `archie/ask/intents/who.py` (`resolve`, `who_intent`, new `unknown_person`)
- Modify: `tests/support/heuristic_llm.py` (route role/title/job questions to `who`; possessive names)
- Test: `tests/unit/test_who.py`, `tests/vignettes/test_m2.py`

**Interfaces:**
- Consumes: `PeopleDirectory.mentioned_in(text, any_case=True)` (Task 1); `search_intent(ctx, question, params) -> Answer` (`archie/ask/intents/search.py`).
- Produces: `PeopleDirectory.names_in(text: str) -> list[str]`; `who.unknown_person(ctx, question: str, params: dict, name: str) -> Answer`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_who.py`, replace `test_unknown_person_says_so` with:

```python
def _cited_answer(system, user, shape, tier):
    ref = next(line for line in user.splitlines() if line.startswith("[") and "SSO dates" in line)[1]
    quote = "Can we ship SSO before the Redis migration?"
    return {"summary": [{"text": "Priya asked about SSO.", "citations": [{"ref": int(ref), "quote": quote}]}],
            "sections": []}


def test_unknown_person_falls_back_to_search(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("who", people=["Zed"], topic="SSO")),
                               answer=_cited_answer))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    out = render(ask(ctx, "who is Zed? something about SSO"))
    assert out.startswith("I didn't recognise anyone called Zed, so I searched everything instead.")
    assert "don't know anyone called" not in out
    assert "answer" in [c["shape"].name for c in fb.calls]  # search really ran


def test_a_topic_word_is_never_taken_for_a_name(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("who", topic="SSO")), answer=_cited_answer))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    out = render(ask(ctx, "who handles SSO?"))
    assert "anyone called SSO" not in out
    assert out.startswith("I couldn't tell who you meant, so I searched everything instead.")


def test_search_finding_nothing_says_so(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("who", people=["Zed"])),
                               answer={"summary": [], "sections": []}))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    assert render(ask(ctx, "who is Zed?")).strip() == \
        "I didn't recognise anyone called Zed, and a search found nothing about it."


def test_code_finds_a_known_name_the_model_missed(tmp_path):
    def answer(system, user, shape, tier):
        return {"summary": [], "sections": []}

    fb = FakeBackend(by_schema(understand=understood(question("who", topic="title")), answer=answer))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    out = render(ask(ctx, "what is priyas title?"))
    assert "Priya Sharma" in out.split("At a glance", 1)[1]
```

In `tests/vignettes/test_m2.py`, after `test_B_ambiguous_name_gets_a_question_not_a_guess`:

```python
def test_B_possessive_question_finds_the_person(tmp_path):
    w = Week(tmp_path)
    for q in ("what is Priya's role?", "what is Priyas role?", "what is priyas role"):
        assert _glance(w.ask(q)).splitlines()[1].strip() == "Priya Sharma", q


def test_B_unknown_or_misspelled_name_gets_a_search_answer(tmp_path):
    w = Week(tmp_path)
    out = w.ask("who is Priyaa?")
    assert out.startswith("I didn't recognise anyone called Priyaa, so I searched everything instead.")
    assert "answer" in w.llm.calls  # the answer came from search
    out = w.ask("what is Zed's role?")
    assert "anyone called role" not in out and "anyone called Zed's" not in out
    assert out.startswith("I didn't recognise anyone called Zed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_who.py tests/vignettes/test_m2.py -q -k "unknown or topic_word or nothing or missed or possessive or misspelled"`
Expected: FAIL ("I don't know anyone called Zed yet." etc.).

- [ ] **Step 3: Implement**

`archie/derive/people.py`, in `PeopleDirectory`:

```python
    def names_in(self, text: str) -> list[str]:
        """People named in the user's message, any case, possessive allowed ("priyas role")."""
        return self.mentioned_in(text, any_case=True)
```

`archie/ask/intents/who.py`, replace `resolve` and the `if not matches:` branch:

```python
_ASKED = re.compile(r"(?:who is|who's|history with)\s+([\w@.\-'’ ]+)", re.I)


def resolve(ctx: Ctx, params: dict, question: str) -> tuple[PeopleDirectory, list[str], str]:
    """(directory, matching ids, the name the user used). A topic is never used as a name."""
    directory = PeopleDirectory.load(ctx.home)
    names = list(params.get("people") or [])
    m = _ASKED.search(question)
    if not names and m:
        names = [m.group(1).strip(" ?")]
    for name in names:
        hits = directory.find(name)
        if hits:
            return directory, hits, name
    found = directory.names_in(question)
    if found:
        return directory, found, directory.name(found[0]).split(" ")[0]
    return directory, [], names[0] if names else ""


def unknown_person(ctx: Ctx, question: str, params: dict, name: str) -> Answer:
    """No known person: search the whole question instead of giving up (spec §4c)."""
    from archie.ask.intents.search import search_intent

    lead = f"I didn't recognise anyone called {name}" if name else "I couldn't tell who you meant"
    answer = search_intent(ctx, question, {**params, "people": []})
    if answer.nothing_found or not (answer.summary or answer.sections):
        return Answer(plain=f"{lead}, and a search found nothing about it.")
    answer.summary.insert(0, Claim(f"{lead}, so I searched everything instead.", []))
    return answer
```

In `who_intent`:

```python
    directory, matches, query = resolve(ctx, params, question)
    if not matches:
        return unknown_person(ctx, question, params, query)
```

`tests/support/heuristic_llm.py`: add a route before `search` and a possessive people pattern.

```python
    (r"\b(role|title|job)\b", "who"),  # add to ROUTES, before the "correct" rule
```

In `_params`, after the existing `people = re.findall(...)`:

```python
    people += re.findall(r"\b([A-Z][a-z]+)(?:'s|’s|s)\s+(?:role|title|job)\b", question)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_who.py tests/vignettes/test_m2.py -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

Update `okf/components/ask.md` (`who`: names from code, fallback to search with the exact code-written lines). Add to `docs/DESIGN.md` §8 where `who` is described: "With no known person, `who` searches the whole question and says so first." Then:

```bash
git add archie/derive/people.py archie/ask/intents/who.py tests/support/heuristic_llm.py tests/unit/test_who.py tests/vignettes/test_m2.py okf/components/ask.md docs/DESIGN.md
git commit -m "who: find known names by code; search instead of 'I don't know anyone called …'"
```

Live check (real home, about 1¢): `uv run archie ask "What is Workpersons title?"` names Workperson (title text arrives in Task 10).

## Step 2 — Usage log (spec §5a)

### Task 3: Log people, topic and sources per ask

**Files:**
- Modify: `archie/ask/pipeline.py` (line 124 `entry["parts"]`, and `ask()` where `entry.update(nothing_found=…)` is)
- Test: `tests/unit/test_ask.py`

**Interfaces:**
- Consumes: `Part.params` (`people`, `topic`), `Answer.packet.items[*].path / .chunk_id`.
- Produces: usage line keys `parts[*].people`, `parts[*].topic`, top-level `sources: list[str]` (`"path#chunk"`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ask.py`:

```python
def test_usage_line_records_people_topic_and_sources(tmp_path):
    import json

    from archie.ask.pipeline import ask
    from archie.derive.people import derive_people
    from archie.llm.backend import FakeBackend
    from tests.support.fixtures import by_schema, make_ctx, question, understood
    from tests.support.raw import addr, msg, write_thread

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(question("search", people=["Priya"], topic="SSO")),
        answer={"summary": [], "sections": []})))
    p = write_thread(ctx.home, "t1", [msg("m1", "priya@acme.example", "Priya Sharma", [addr("test@acme.example")],
                                          "2026-09-22T17:00:00+00:00", "Can we ship SSO first?", to_me=True)])
    derive_people(ctx, [p])
    ctx.index.sync()
    ask(ctx, "what did Priya say about SSO?")
    line = json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1])
    assert line["parts"][0]["people"] == ["Priya"] and line["parts"][0]["topic"] == "SSO"
    assert "sources/gmail/t1.json#c0" in line["sources"]
```

(If `test_ask.py` reads the log from a different path helper, use that; the usage log is `logs/usage.jsonl` under the home.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_ask.py -q -k usage_line`
Expected: FAIL (`KeyError: 'people'`).

- [ ] **Step 3: Implement**

`archie/ask/pipeline.py` line 124:

```python
    entry["parts"] = [{"kind": p.kind, "handler": label, "people": p.params.get("people") or [],
                       "topic": p.params.get("topic")} for p, (label, _) in zip(parts, handled)]
```

In `ask()`, inside the `entry.update(...)` call, add:

```python
                     sources=[f"{it.path}#{it.chunk_id}" for it in answer.packet.items],
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_ask.py -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

Update `docs/REVIEW.md` §2 table row for `logs/usage.jsonl` (parts now carry `people` and `topic`; `sources` lists what the model saw) and `okf/components/ask.md`.

```bash
git add archie/ask/pipeline.py tests/unit/test_ask.py docs/REVIEW.md okf/components/ask.md
git commit -m "Usage log: people and topic per part, and the sources the model saw"
```

## Step 3 — Evidence selector (spec §2)

### Task 4: `person_evidence`, adopted by `who`

**Files:**
- Create: `archie/ask/evidence.py`
- Modify: `archie/index/db.py` (`chunks_with_people` also returns `sender`, lines 143–156)
- Modify: `archie/ask/intents/who.py` (packet loop, lines 103–112)
- Test: `tests/unit/test_evidence.py` (new), `tests/vignettes/test_m2.py`

**Interfaces:**
- Consumes: `Index.chunks_with_people(emails, limit, before) -> list[dict]` (now with `"sender"`); `search(idx, query, k, since, until, people) -> list[Hit]`.
- Produces: `person_evidence(ctx, entity_id: str, *, topic: str | None = None, max_items: int = 40, max_chars: int = 160_000, since: str | None = None) -> list[dict]` (dicts with `path, chunk_id, text, source, ts, label, sender`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_evidence.py`:

```python
from archie.ask.evidence import person_evidence
from archie.derive.people import PeopleDirectory, derive_people
from archie.store.files import Note, write_note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

ME, LEE = "test@acme.example", "lee@park.example"


def seed(ctx, copied=15):
    paths = [write_thread(ctx.home, "own", [msg("o1", LEE, "Lee Park", [addr(ME)], "2026-09-01T10:00:00+00:00",
                                                "I lead the data platform team.", to_me=True)])]
    paths += [write_thread(ctx.home, f"cc{i}", [msg(f"c{i}", "hr@acme.example", "HR", [addr(ME)],
                                                    f"2026-09-{10 + i:02d}T10:00:00+00:00", f"Benefits form {i}.",
                                                    cc=[addr(LEE, "Lee Park")], to_me=True)])
              for i in range(copied)]
    derive_people(ctx, paths)
    ctx.index.sync()
    return PeopleDirectory.load(ctx.home).by_email(LEE)


def test_own_messages_come_before_newer_copied_ones(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    got = person_evidence(ctx, eid, max_items=5)
    assert got[0]["path"] == "sources/gmail/own.json"
    assert len(got) == 5


def test_a_topic_ranks_first(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    got = person_evidence(ctx, eid, topic="Benefits form 3", max_items=3)
    assert got[0]["path"] == "sources/gmail/cc3.json"


def test_budget_skips_a_chunk_too_big_but_keeps_going(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx, copied=3)
    got = person_evidence(ctx, eid, max_chars=200)
    assert got and sum(len(c["text"]) for c in got) <= 200


def test_person_without_addresses_has_no_evidence(tmp_path):
    ctx = make_ctx(tmp_path)
    write_note(ctx.home / "people/acorn.md", Note(meta={"entity_id": "acorn", "name": "Acorn", "aliases": []},
                                                  body="## My notes\n- Acorn is three. _(you said, Oct 4)_\n"))
    assert person_evidence(ctx, "acorn") == []
```

In `tests/vignettes/test_m2.py`:

```python
def test_B_topic_in_a_long_history_reaches_the_answer(tmp_path):
    from archie.derive.people import derive_people
    from tests.support.raw import addr, msg, write_thread

    w = Week(tmp_path)
    lee = "lee@park.example"
    paths = [write_thread(w.ctx.home, "lee_old", [msg("l0", lee, "Lee Park", [addr(ME)], "2026-08-01T10:00:00+00:00",
                                                     "The CPS report was false.", subject="School", to_me=True)])]
    paths += [write_thread(w.ctx.home, f"lee{i}", [msg(f"l{i}", lee, "Lee Park", [addr(ME)],
                                                       f"2026-09-{1 + i % 28:02d}T{10 + i // 28}:00:00+00:00",
                                                       f"Swim practice note {i}.", subject="Swim", to_me=True)])
              for i in range(50)]
    derive_people(w.ctx, paths)
    w.ctx.index.sync()
    w.ctx.config["ask"]["max_sources"] = 10
    w.llm.prompts.clear()
    w.ask("Tell me about Lee and CPS")
    assert "The CPS report was false." in w.llm.saw("answer")
```

For that vignette to route to `who` with a topic, extend `tests/support/heuristic_llm.py` `_params`: when the message matches `r"tell me about ([A-Z][a-z]+) and (\w+)"`, set `people=[group 1]`, `topic=group 2`, and add `(r"\btell me about\b", "who")` to `ROUTES` just before `search`. Check that `uv run pytest tests/vignettes -q` stays green after the route change. If an existing vignette asks "tell me about …" expecting search, narrow the route to `r"\btell me about [A-Z][a-z]+\b(?: and \w+)?\??$"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_evidence.py tests/vignettes/test_m2.py -q -k "evidence or own_messages or topic or budget or addresses or long_history"`
Expected: FAIL (`ModuleNotFoundError: archie.ask.evidence`).

- [ ] **Step 3: Implement**

`archie/index/db.py` `chunks_with_people`: select `sender` too.

```python
        rows = self.query(
            f"SELECT path, chunk_id, text, source, ts, label, sender FROM chunks WHERE {where} ORDER BY ts DESC LIMIT ?",
            args + [limit])
        return [dict(zip(("path", "chunk_id", "text", "source", "ts", "label", "sender"), r)) for r in rows]
```

`archie/ask/evidence.py`:

```python
"""The one way to gather evidence about a person (spec: durable-fixes §2).

Order: chunks matching the topic (if any), then chunks the person sent, then the rest of
their chunks, each newest first, within an item count and a character budget. A chunk too
big for the room left is skipped, not the rest. Archie's own notes (dossiers, loops,
briefings) are left out; future meetings too."""

from __future__ import annotations

from archie.ask.context import Ctx

SKIP = ("briefings", "loops", "people")


def person_evidence(ctx: Ctx, entity_id: str, *, topic: str | None = None, max_items: int = 40,
                    max_chars: int = 160_000, since: str | None = None) -> list[dict]:
    from archie.derive.people import PeopleDirectory
    from archie.index.search import search

    ids = PeopleDirectory.load(ctx.home).identifiers(entity_id)
    if not ids or max_items <= 0:
        return []
    before = ctx.now.isoformat()
    theirs = [c for c in ctx.index.chunks_with_people(ids, limit=100_000, before=before)
              if c["source"] not in SKIP and (not since or (c["ts"] or "") > since)]
    by_key = {(c["path"], c["chunk_id"]): c for c in theirs}
    ordered: list[dict] = []
    if topic:
        hits = search(ctx.index, topic, k=max_items, people=ids, since=since, until=before)
        ordered += [by_key[(h.path, h.chunk_id)] for h in hits if (h.path, h.chunk_id) in by_key]
    senders = {i.lower() for i in ids}
    ordered += [c for c in theirs if (c.get("sender") or "").lower() in senders]
    ordered += theirs
    out, seen, used = [], set(), 0
    for c in ordered:
        key = (c["path"], c["chunk_id"])
        if key in seen or len(out) >= max_items:
            continue
        if used + len(c["text"]) > max_chars:
            continue
        seen.add(key)
        out.append(c)
        used += len(c["text"])
    return out
```

`archie/ask/intents/who.py`, replace the `for c in history:` packet loop (keep `history` for "Recent" and the thread count):

```python
    from archie.ask.evidence import person_evidence

    for c in person_evidence(ctx, eid, topic=params.get("topic"), max_items=k - len(packet.items), max_chars=room):
        packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_evidence.py tests/unit/test_who.py tests/vignettes -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

`okf/components/ask.md`: add `evidence.py` (order, budget, callers). `okf/components/index-search.md`: `chunks_with_people` returns `sender`.

```bash
git add archie/ask/evidence.py archie/index/db.py archie/ask/intents/who.py tests/unit/test_evidence.py tests/vignettes/test_m2.py tests/support/heuristic_llm.py okf/components/ask.md okf/components/index-search.md
git commit -m "One evidence selector for a person: topic, their own messages, then the rest; who uses it"
```

### Task 5: Briefings use the selector

**Files:**
- Modify: `archie/briefings/build.py` (`gather`, the per-attendee loop around line 146)
- Test: `tests/unit/test_briefings.py`

**Interfaces:**
- Consumes: `person_evidence` (Task 4).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_briefings.py`. One attendee (Lee) sent an email on Sep 25 and was only copied on 15 newer HR threads. The meeting title is a single word of three or more letters ("Catch up"), so the title search adds nothing and only the attendee loop can bring Lee's email in:

```python
def test_attendee_context_puts_their_own_mail_first(tmp_path):
    seen = {}

    def capture(system, user, schema, tier):
        seen["user"] = user
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer=capture)), now=NOW)
    ev = cal_event("ev9", "Catch up", "2026-10-01T21:00:00Z", "2026-10-01T21:30:00Z",
                   attendees=[("test@acme.example", "Test"), ("lee@park.example", "Lee Park")])
    paths = [ctx.home / "sources/calendar/ev9.json"]
    write_raw(paths[0], normalize_event(ev, TEST))
    paths.append(write_thread(ctx.home, "plan", [
        msg("p1", "lee@park.example", "Lee Park", [addr("test@acme.example")], "2026-09-25T17:00:00+00:00",
            "Here is the rollout plan.", subject="Plan", to_me=True)]))
    paths += [write_thread(ctx.home, f"hr{i}", [
        msg(f"h{i}", "hr@acme.example", "HR", [addr("test@acme.example")],
            f"2026-09-{26 + i % 5:02d}T{10 + i // 5}:00:00+00:00", f"Benefits form {i}.", subject=f"Form {i}",
            cc=[addr("lee@park.example", "Lee Park")], to_me=True)]) for i in range(15)]
    derive_people(ctx, paths)
    derive_meetings(ctx, paths)
    ctx.index.sync()
    build_briefing(ctx, pick_meeting(ctx, None))
    assert "Here is the rollout plan." in seen["user"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_briefings.py -q -k own_mail_first`
Expected: FAIL (the 12-newest window holds only the HR threads).

- [ ] **Step 3: Implement**

In `gather`, replace the `chunks_with_people(..., limit=12, ...)` loop:

```python
    if kind != "all_hands" and kind != "standup":
        from archie.ask.evidence import person_evidence

        for eid in m.meta.get("attendees") or []:
            for c in ctx.index.chunks_of(f"people/{eid}.md")[:3]:
                p.add(c["path"], c["chunk_id"], c["text"], label=c["label"])
            for c in person_evidence(ctx, eid, max_items=12, since=since):
                p.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
                if len(p.items) > 24:
                    break
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_briefings.py tests/vignettes -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`okf/components/briefings.md`: attendee context comes from `person_evidence`.

```bash
git add archie/briefings/build.py tests/unit/test_briefings.py okf/components/briefings.md
git commit -m "Briefings: attendee context from the evidence selector"
```

## Step 4 — Re-derivation (spec §1)

### Task 6: Version stamps; people-facts rebuilds read everything

**Files:**
- Create: `archie/derive/versions.py`
- Modify: `archie/derive/enrich.py` (`prompt_version`, `_enrich_one`)
- Modify: `archie/config.py` (`DEFAULTS["people"] = {"facts_max_chars": 40_000}`)
- Test: `tests/unit/test_enrich.py`

**Interfaces:**
- Consumes: `person_evidence` (Task 4).
- Produces: `stamp(name: str, *parts: object) -> str`; `enrich._batches(chunks: list[dict], max_chars: int) -> list[list[dict]]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_enrich.py`:

```python
def test_rebuild_reads_old_material_beyond_the_newest_dozen(tmp_path):
    seen = []

    def reply(s, u, sc, t):
        seen.append(u)
        if "Director of Engineering" in u:
            ref = next(line for line in u.splitlines() if line.startswith("[") and "Intro" in line)[1]
            return {"facts": [{"text": "Director of Engineering", "ref": int(ref), "quote": "Director of Engineering"}]}
        return {"facts": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=reply)))
    paths = [write_thread(ctx.home, "intro", [msg("i1", "workperson@ow.example", "Workperson Acorn", [addr(TEST)],
                                                  "2026-09-01T00:00:00+00:00", "Meet Mike. I am the Director of Engineering here.",
                                                  subject="Intro", to_me=True)])]
    paths += [write_thread(ctx.home, f"cc{i}", [msg(f"c{i}", "hr@ow.example", "HR", [addr(TEST)],
                                                    f"2026-09-{10 + i:02d}T00:00:00+00:00", f"Form {i}.",
                                                    cc=[addr("workperson@ow.example", "Workperson Acorn")], to_me=True)])
              for i in range(15)]
    derive_people(ctx, paths)
    ctx.index.sync()
    enrich_people(ctx)
    assert "Director of Engineering" in get_fence(read_note(ctx.home / "people/workperson_acorn.md").body)


def test_batches_are_oldest_first_and_within_budget():
    from archie.derive.enrich import _batches

    chunks = [{"ts": f"2026-09-0{i}", "text": "x" * 40} for i in (3, 1, 2)]
    out = _batches(chunks, 90)
    assert [[c["ts"] for c in b] for b in out] == [["2026-09-01", "2026-09-02"], ["2026-09-03"]]


def test_a_failed_batch_writes_nothing(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))  # every call raises LLMError
    seed(ctx)
    before = read_note(ctx.home / "people/workperson_acorn.md").body
    enrich_people(ctx)
    assert read_note(ctx.home / "people/workperson_acorn.md").body == before
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_enrich.py -q`
Expected: the first and second new tests FAIL; the third may already pass (keep it as a guard).

- [ ] **Step 3: Implement**

`archie/derive/versions.py`:

```python
"""Which version of a deriver's logic produced something (spec: durable-fixes §1a). When the
stamp changes, the derivation is redone from the files."""

from __future__ import annotations

import hashlib


def stamp(name: str, *parts: object) -> str:
    text = "\n".join([name, *map(str, parts)])
    return hashlib.sha256(text.encode()).hexdigest()[:12]
```

`archie/config.py` `DEFAULTS`: add `"people": {"facts_max_chars": 40_000},  # one people-facts call reads at most this much`.

`archie/derive/enrich.py`:

```python
from archie.derive.versions import stamp


def prompt_version() -> str:
    """Changes whenever people_facts.md, the reply shape or INSTRUCTIONS_VERSION changes."""
    return stamp("people_facts", INSTRUCTIONS_VERSION, load_prompt("people_facts"), repr(SHAPE))


def _batches(chunks: list[dict], max_chars: int) -> list[list[dict]]:
    """Oldest first, each batch within max_chars (a single bigger chunk gets its own batch)."""
    out, cur, used = [], [], 0
    for c in sorted(chunks, key=lambda c: c["ts"] or ""):
        if cur and used + len(c["text"]) > max_chars:
            out.append(cur)
            cur, used = [], 0
        cur.append(c)
        used += len(c["text"])
    return out + ([cur] if cur else [])
```

Replace `_enrich_one` with:

```python
def _enrich_one(ctx: Ctx, directory: PeopleDirectory, eid: str, since: str, failures: Failures,
                fresh: bool = False) -> str | None:
    """Update one dossier; returns the newest chunk time considered, or None if skipped.
    A redo (new instructions, something the user told us, or an old fact using a ruled-out word)
    reads all of the person's material in batches; otherwise only what's newer than `since`.
    Nothing is written unless every batch succeeds."""
    from archie.ask.evidence import person_evidence
    from archie.ask.synthesize import describe, people_context

    path = ctx.home / f"people/{eid}.md"
    redo = fresh or bool(directory.meta.get(eid, {}).get("facts_stale"))
    everything = person_evidence(ctx, eid, max_items=100_000, max_chars=10**12)
    if not everything:
        return None
    avoid = directory.avoided_words(
        [eid, *directory.mentioned_in(" ".join(f"{c['label']} {c['text']}" for c in everything))])
    if any(_uses(f["text"], avoid) for f in parse_facts(get_fence(read_note(path).body))):
        redo = True
    chunks = everything if redo else [c for c in everything if (c["ts"] or "") > since]
    newest = max((c["ts"] or "" for c in everything), default="")
    if not chunks or failures.gave_up(f"people:{eid}", newest):
        return None
    name = directory.name(eid)
    system = load_prompt("people_facts", person=name, me_name=ctx.me.name or "the user")
    told = describe(directory.meta.get(eid, {}), name)
    mine = read_note(path).body.split("<!-- archie:auto -->")[0].replace("## My notes", "").strip()
    if told or mine:
        system += ("\n\nWhat the user has told you about them is ground truth. Never state a fact that "
                   "contradicts it (e.g. if they say 'my child', never write 'son'). Don't repeat it "
                   "(Archie shows it in their own words); add what the sources show beyond it: where they "
                   "work or study, what they do, what they care about.\n"
                   + (f"Stated: {told}\n" if told else "") + (f"Their notes:\n{mine}" if mine else ""))
    if newest and (ctx.now - datetime.fromisoformat(newest).replace(tzinfo=ctx.now.tzinfo)).days > OLD_DAYS:
        system += (f"\n\nThe newest source is from {newest[:4]}, over a year ago. Write each fact in the past "
                   f"tense with its year (\"In {newest[:4]}, handled your app issue\"), never as if it's current.")
    note = read_note(path)
    facts = [] if redo else [f for f in parse_facts(get_fence(note.body)) if not _uses(f["text"], avoid)]
    for batch in _batches(chunks, int(ctx.config["people"]["facts_max_chars"])):
        packet = Packet()
        for c in batch:
            packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
        user = f"{people_context(ctx, packet)}\n\nSources about {name}:\n\n{packet.render()}".lstrip()
        try:
            out = ctx.backend.complete(system, user, SHAPE, tier="fast")
        except LLMError as exc:
            failures.failed(f"people:{eid}", newest, exc)
            return None
        for f in out.get("facts") or []:
            cite = check_quote(packet, int(f.get("ref", 0)), f.get("quote", ""))
            if cite is None or not f.get("text") or _uses(f["text"], avoid):
                continue
            new = {"text": f["text"].strip().rstrip("."), "file": cite.path, "chunk": cite.chunk_id,
                   "quote": cite.quote.replace('"', "'")}
            facts = [x for x in facts if normalize(x["text"]) != normalize(new["text"])] + [new]
    failures.ok(f"people:{eid}")
    note.meta.pop("facts_stale", None)
    note.body = set_fence(note.body, render_facts(note.meta, facts[-MAX_FACTS:]))
    write_note(path, note)
    return newest
```

The avoided-word check reads `everything` (not just the new chunks), matching today's behaviour of checking the whole packet. `packet_text` is no longer imported here.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_enrich.py -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

`okf/components/enrich.md`: replace "the person's 12 most recent chunks" with the evidence selector, batches of `people.facts_max_chars` and the version stamp. `okf/components/config.md`: `people.facts_max_chars`. `okf/components/derivers.md`: `versions.py`. Note in `okf/log.md` that the new stamp rebuilds every dossier once on the next sync (about $0.30 on the real home).

```bash
git add archie/derive/versions.py archie/derive/enrich.py archie/config.py tests/unit/test_enrich.py okf/components/enrich.md okf/components/config.md okf/components/derivers.md okf/log.md
git commit -m "People facts: version stamps; rebuilds read all of a person's material in batches"
```

### Task 7: Replay person tellings; sync report notes

**Files:**
- Create: `archie/derive/replay.py`
- Modify: `archie/ask/remember.py` (`REMEMBER_VERSION = 1`; `apply_facts(..., changed_only=False)`; `remember_people(..., changed_only=False)`)
- Modify: `archie/derive/registry.py` (`post_index_steps` → `[replay_tellings, enrich_people, audit]`)
- Modify: `archie/sync.py` (`run_cycle(..., notes: list[str] | None = None)`)
- Modify: `archie/tui/app.py` (`sync_cycle`), `archie/cli.py` (sync command)
- Test: `tests/unit/test_replay.py` (new), `tests/unit/test_sync.py`, `tests/vignettes/test_n_telling.py`

**Interfaces:**
- Consumes: `stamp` (Task 6); `remember_people`; `Failures(home)` with `gave_up(key, marker)`, `failed(key, marker, exc)`, `ok(key)`, `save()`; `SAVED_ONLY`, `TOLD` from `archie/ask/tell.py`.
- Produces: `replay.remember_version() -> str`; `replay.told_lines(home) -> list[tuple[str, str, str]]` (key, text, result); `replay.replay_tellings(ctx) -> list[str]`; `run_cycle(..., notes=...)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_replay.py`:

```python
from archie.derive.replay import replay_tellings, told_lines
from archie.llm.backend import FakeBackend
from archie.store.files import Note, read_note, write_note
from tests.support.fixtures import by_schema, make_ctx

HEAD = "# What you told Archie\n\nArchie adds a line each time you tell it something. You can edit this file.\n\n"
ENERGY = "Acorn is full of energy and is 3 and a half years old."


def told(ctx, *lines):
    (ctx.home / "journal").mkdir(exist_ok=True)
    (ctx.home / "journal/told.md").write_text(HEAD + "".join(f"{x}\n" for x in lines))


def acorn(ctx):
    write_note(ctx.home / "people/acorn.md", Note(meta={"entity_id": "acorn", "name": "Acorn", "aliases": [],
                                                        "relationship": "kid"}, body="## My notes\n"))


def person(name, statement, **kw):
    return {"people": [{"name": name, "statement": statement, **kw}]}


def test_saved_only_person_telling_reaches_their_notes_once(tmp_path):
    fb = FakeBackend(by_schema(remember=person("Acorn", ENERGY)))
    ctx = make_ctx(tmp_path, fb)
    acorn(ctx)
    told(ctx, f'- 2026-10-04 · "{ENERGY}" → saved only')
    assert replay_tellings(ctx) == ["Re-applied 1 thing you told me earlier: Acorn"]
    assert ENERGY in read_note(ctx.home / "people/acorn.md").body
    calls = len(fb.calls)
    assert replay_tellings(ctx) == [] and len(fb.calls) == calls  # same version: nothing redone


def test_later_correction_still_wins(tmp_path):
    def reply(system, user, shape, tier):
        rel = "cousin" if "cousin" in user else "neighbor"
        return person("Sam", user.strip(), relationship=rel)

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(remember=reply)))
    told(ctx, '- 2026-10-03 · "Sam is my neighbor." → remembered: Sam, new',
         '- 2026-10-04 · "Sam is my cousin." → remembered: Sam')
    replay_tellings(ctx)
    assert read_note(ctx.home / "people/sam.md").meta["relationship"] == "cousin"


def test_ignore_lines_and_other_results_are_not_replayed(tmp_path):
    fb = FakeBackend([])
    ctx = make_ctx(tmp_path, fb)
    told(ctx, '- 2026-10-03 · "x@y.co is spam, ignore it" → ignoring x@y.co',
         '- 2026-10-03 · "only show work stuff on weekdays" → can\'t do this yet')
    assert replay_tellings(ctx) == [] and fb.calls == []


def test_a_failed_call_records_no_version_and_retries(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))  # raises LLMError
    acorn(ctx)
    told(ctx, f'- 2026-10-04 · "{ENERGY}" → saved only')
    assert replay_tellings(ctx) == []
    ctx.backend = FakeBackend(by_schema(remember=person("Acorn", ENERGY)))
    assert replay_tellings(ctx) == ["Re-applied 1 thing you told me earlier: Acorn"]


def test_hand_edited_or_missing_file_is_fine(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    assert replay_tellings(ctx) == []  # no told.md
    told(ctx, "- a line I typed myself", "", "- 2026-10-04 · no quotes → saved only")
    assert told_lines(ctx.home) == [] and replay_tellings(ctx) == []


def test_unchanged_people_are_not_reported(tmp_path):
    fb = FakeBackend(by_schema(remember=person("Acorn", ENERGY)))
    ctx = make_ctx(tmp_path, fb)
    acorn(ctx)
    told(ctx, f'- 2026-10-04 · "{ENERGY}" → saved only', f'- 2026-10-05 · "{ENERGY} " → saved only')
    assert replay_tellings(ctx) == ["Re-applied 1 thing you told me earlier: Acorn"]
```

Append to `tests/unit/test_sync.py`:

```python
def test_post_index_sentences_reach_notes(tmp_path):
    ctx = make_ctx(tmp_path)
    notes: list[str] = []
    asyncio.run(run_cycle(ctx, [], post_index=[lambda c: ["Re-applied 1 thing you told me earlier: Acorn"],
                                               lambda c: None], notes=notes))
    assert notes == ["Re-applied 1 thing you told me earlier: Acorn"]
```

Append to `tests/vignettes/test_n_telling.py` (add `import asyncio`, `from archie.derive.registry import post_index_steps`, `from archie.store.files import read_note, write_note`, `from archie.sync import run_cycle`, and `by_schema` from `tests.support.fixtures` to the imports):

```python
def test_N_telling_saved_before_a_fix_reaches_the_person(tmp_path):
    energy = "Acorn is full of energy and is 3 and a half years old."
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        remember={"people": [{"name": "Acorn", "statement": energy}]},
        people_facts={"facts": []})))
    write_note(ctx.home / "people/acorn.md", Note(meta={"entity_id": "acorn", "name": "Acorn", "aliases": [],
                                                        "relationship": "kid"}, body="## My notes\n"))
    (ctx.home / "journal").mkdir(exist_ok=True)
    (ctx.home / "journal/told.md").write_text(
        "# What you told Archie\n\n" f'- 2026-10-04 · "{energy}" → saved only\n')
    notes: list[str] = []
    asyncio.run(run_cycle(ctx, [], post_index=post_index_steps(), notes=notes))
    assert energy in read_note(ctx.home / "people/acorn.md").body
    assert "Re-applied 1 thing you told me earlier: Acorn" in notes
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_replay.py tests/unit/test_sync.py tests/vignettes/test_n_telling.py -q`
Expected: FAIL (`ModuleNotFoundError: archie.derive.replay`).

- [ ] **Step 3: Implement**

`archie/ask/remember.py`: add `REMEMBER_VERSION = 1  # bump when apply_facts or the remember instructions change` near `SHAPE`. Then change `apply_facts` and `remember_people`. Only the marked lines are new; the rest of `apply_facts` stays as it is:

```python
def _content(note: Note) -> tuple[dict, str]:
    return {k: v for k, v in note.meta.items() if k != "facts_stale"}, note.body


def apply_facts(ctx: Ctx, question: str, people: list[dict], changed_only: bool = False) -> list[str]:
    ...
        path = ctx.home / f"people/{eid}.md"
        note = read_note(path)
        before = copy.deepcopy(_content(note))                      # new
        for key in ("relationship", "role", "pronouns", "identity"):
            ...
        if statement and normalize(statement) in normalize(question):
            _add_note(note, statement, when)
        if changed_only and _content(note) == before:               # new: a replay that changes nothing
            continue                                                #      writes nothing and isn't reported
        write_note(path, note)
        ...


def remember_people(ctx: Ctx, said: str, changed_only: bool = False) -> list[str]:
    """Apply what the user said about people; one line per person changed (or a "Which …?").
    `changed_only` (replays): skip people the sentence no longer changes."""
    out = ctx.backend.complete(load_prompt("remember", me_name=ctx.me.name or "the user"), said, SHAPE)
    return apply_facts(ctx, said, out.get("people") or [], changed_only=changed_only)
```

Add `import copy` (`Note` is already imported). Leaving `facts_stale` out of the comparison matters: `apply_facts` always sets it, so comparing it would report every replayed person as changed and rebuild every dossier.

`archie/derive/replay.py`:

```python
"""Re-apply what the user told Archie about people when the remember logic changes
(spec: durable-fixes §1c). journal/told.md is never changed; which version last applied each
line is kept in state/told_applied.yaml. Only person tellings are replayed, in told order,
so a later correction still wins."""

from __future__ import annotations

import hashlib
import re

import yaml

from archie.ask.context import Ctx
from archie.derive.failures import Failures
from archie.derive.versions import stamp
from archie.llm.backend import LLMError
from archie.store.files import atomic_write

STATE = "state/told_applied.yaml"
LINE = re.compile(r'^- (\d{4}-\d\d-\d\d) · "(.+)" → (.+)$')


def remember_version() -> str:
    from archie.ask.remember import REMEMBER_VERSION, SHAPE
    from archie.llm.prompts import load_prompt

    return stamp("remember", REMEMBER_VERSION, load_prompt("remember"), repr(SHAPE))


def told_lines(home) -> list[tuple[str, str, str]]:
    from archie.ask.tell import TOLD

    path = home / TOLD
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line.strip())
        if m:
            day, text, result = m.groups()
            out.append((hashlib.sha1(f"{day}|{text}".encode()).hexdigest()[:12], text, result))
    return out


def _replayable(result: str) -> bool:
    from archie.ask.tell import SAVED_ONLY

    return result == SAVED_ONLY or result.startswith("remembered:")


def replay_tellings(ctx: Ctx) -> list[str]:
    from archie.ask.remember import remember_people

    version = remember_version()
    path = ctx.home / STATE
    state = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    applied = state.get("applied") or {}
    failures = Failures(ctx.home)
    changed: list[str] = []
    for key, text, result in told_lines(ctx.home):
        if not _replayable(result) or applied.get(key) == version or failures.gave_up(f"told:{key}", version):
            continue
        try:
            lines = remember_people(ctx, text, changed_only=True)
        except LLMError as exc:
            failures.failed(f"told:{key}", version, exc)
            continue
        failures.ok(f"told:{key}")
        applied[key] = version
        changed += [x.split(":")[0].removesuffix(", new") for x in lines if not x.startswith("Which ")]
    failures.save()
    if applied != (state.get("applied") or {}):
        atomic_write(path, yaml.safe_dump({"applied": applied}, sort_keys=True))
    names = list(dict.fromkeys(changed))
    if not names:
        return []
    n = len(names)
    return [f"Re-applied {n} thing{'' if n == 1 else 's'} you told me earlier: {', '.join(names)}"]
```


`archie/derive/registry.py`:

```python
def post_index_steps() -> list:
    """Run after indexing, because they read the index."""
    from archie.derive.audit import audit
    from archie.derive.enrich import enrich_people
    from archie.derive.replay import replay_tellings

    return [replay_tellings, enrich_people, audit]
```

`archie/sync.py` `run_cycle`: add `notes: list[str] | None = None` to the signature, and in the post-index loop:

```python
        for step in post_index or []:
            out = await asyncio.to_thread(step, ctx)
            if notes is not None and isinstance(out, list):
                notes += [str(x) for x in out]
```

`archie/tui/app.py` `sync_cycle`: create `notes: list[str] = []`, pass `notes=notes`, and add `lines += notes` before `self.finish_sync_report(...)`. `archie/cli.py` sync: pass `notes=notes` and `print(*notes, sep="\n")` after the connector lines when `notes` isn't empty.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_replay.py tests/unit/test_remember.py tests/unit/test_tell.py tests/unit/test_sync.py tests/vignettes/test_n_telling.py -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

`okf/components/derivers.md` (`replay.py`, `state/told_applied.yaml`), `okf/components/sync.md` (post-index notes), `docs/DESIGN.md` §4 storage layout (`state/told_applied.yaml`) and §4.2 ("tellings are re-applied when the remember logic changes"), `okf/log.md`.

```bash
git add archie/derive/replay.py archie/ask/remember.py archie/derive/registry.py archie/sync.py archie/tui/app.py archie/cli.py tests/unit/test_replay.py tests/unit/test_sync.py tests/vignettes/test_n_telling.py okf/components/derivers.md okf/components/sync.md docs/DESIGN.md okf/log.md
git commit -m "Replay person tellings when the remember logic changes; sync report says what changed"
```

Live check: one `uv run archie admin sync` (or a TUI sync) on the real home; Acorn's notes gain "full of energy…" and Acorn/Childone get `full_name`; the report lists them.

### Task 8: Loops record their version; doctor reports older ones

**Files:**
- Modify: `archie/derive/loops.py` (`derive_loops`)
- Modify: `archie/doctor.py` (new `check_loop_versions`, added in `run_checks`)
- Test: `tests/unit/test_loops.py`, `tests/unit/test_doctor.py`

**Interfaces:**
- Consumes: `stamp` (Task 6).
- Produces: `loops.loop_version() -> str`; `loops_seen.yaml` gains a top-level `_versions: {thread_id: stamp}`; `doctor.check_loop_versions(home) -> Check | None`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_loops.py`: after one `derive_loops` run over a thread (use the file's existing extraction fixture), `yaml.safe_load(loops_seen)["_versions"][tid] == loop_version()`. `tests/unit/test_doctor.py`: with `loops_seen.yaml` holding `{"t1": "2026-09-01T00:00:00+00:00", "t2": "…", "_versions": {"t2": loop_version()}}`, `check_loop_versions(home)` returns `(True, "1 email thread was read for open items by older instructions; Archie doesn't re-read it automatically.")`; with every thread current it returns `None`.

```python
def test_loop_versions_reports_older_threads(tmp_path):
    import yaml

    from archie.derive.loops import loop_version
    from archie.doctor import check_loop_versions
    from tests.support.fixtures import make_ctx

    ctx = make_ctx(tmp_path)
    (ctx.home / "state/loops_seen.yaml").write_text(yaml.safe_dump(
        {"t1": "2026-09-01T00:00:00+00:00", "t2": "2026-09-02T00:00:00+00:00", "_versions": {"t2": loop_version()}}))
    assert check_loop_versions(ctx.home) == (
        True, "1 email thread was read for open items by older instructions; Archie doesn't re-read it automatically.")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_loops.py tests/unit/test_doctor.py -q -k version`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

`archie/derive/loops.py`:

```python
def loop_version() -> str:
    from archie.derive.versions import stamp
    from archie.llm.prompts import load_prompt

    return stamp("loops", load_prompt("loops_extract"), load_prompt("loops_close"))
```

In `derive_loops`, after loading `seen`: `versions = seen.pop("_versions", None) or {}` and `version = loop_version()`. When a result is recorded (`seen[result[0]] = result[1]`), also set `versions[result[0]] = version`. Every `atomic_write` of `seen` writes `{**seen, "_versions": versions}`.

`archie/doctor.py`:

```python
def check_loop_versions(home: Home) -> Check | None:
    import yaml

    from archie.derive.loops import loop_version

    path = home / "state/loops_seen.yaml"
    seen = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    versions = seen.pop("_versions", None) or {}
    current = loop_version()
    n = sum(1 for tid in seen if versions.get(tid) != current)
    if not n:
        return None
    return True, (f"{n} email thread{' was' if n == 1 else 's were'} read for open items by older instructions; "
                  f"Archie doesn't re-read {'it' if n == 1 else 'them'} automatically.")
```

Add it to `run_checks` next to `check_failures`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_loops.py tests/unit/test_doctor.py -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`okf/components/loops.md`, `okf/components/doctor.md`.

```bash
git add archie/derive/loops.py archie/doctor.py tests/unit/test_loops.py tests/unit/test_doctor.py okf/components/loops.md okf/components/doctor.md
git commit -m "Loops record their instructions' version; doctor counts threads read by older ones"
```

## Step 5 — Signatures and titles (spec §3)

### Task 9: Signatures become their own chunks

**Files:**
- Modify: `archie/connectors/gmail.py` (`clean_body` → `split_body`; `chunk_thread`)
- Modify: `archie/index/chunk.py` (`CHUNKER_VERSION = "3"`)
- Test: `tests/unit/test_gmail.py`

**Interfaces:**
- Produces: `split_body(body: str) -> tuple[str, str]` (message, signature); signature chunks with `chunk_id == f"s{i}"`, `people == [sender]`, `label == f"Signature of {who} ({when(date)})"`. `clean_body(body)` stays and returns `split_body(body)[0]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_gmail.py`:

```python
from archie.connectors.gmail import chunk_thread, clean_body, split_body

SIG_CRLF = "Thanks,\r\n  Workperson\r\n\r\n-- \r\nWorkperson Acorn\r\nDirector of Engineering\r\n781-526-7220"


def test_crlf_and_lf_mail_strip_the_same():
    assert clean_body(SIG_CRLF) == clean_body(SIG_CRLF.replace("\r\n", "\n")) == "Thanks,\n  Workperson"
    assert split_body(SIG_CRLF)[1] == "Workperson Acorn\nDirector of Engineering\n781-526-7220"


def test_signature_is_its_own_chunk():
    data = {"id": "t1", "messages": [{"id": "m1", "from_email": "workperson@ow.example", "from_name": "Workperson Acorn",
                                      "to": [{"email": "test@acme.example", "name": "Test"}], "cc": [],
                                      "date": "2026-09-22T20:16:16+00:00", "subject": "Incoming Offer",
                                      "body": SIG_CRLF, "from_me": False}]}
    chunks = chunk_thread("sources/gmail/t1.json", data)
    assert [c.chunk_id for c in chunks] == ["c0", "s0"]
    sig = chunks[1]
    assert sig.text == "Workperson Acorn\nDirector of Engineering\n781-526-7220"
    assert sig.people == ["workperson@ow.example"] and sig.sender == "workperson@ow.example"
    assert sig.label.startswith("Signature of Workperson Acorn (")
    assert "Director of Engineering" not in chunks[0].text


def test_quoted_signatures_make_no_chunk():
    body = "Thanks Workperson!\r\n\r\nOn Tue, Sep 22, 2026 at 1:16 PM Workperson Acorn <k@ow.example> wrote:\r\n> --\r\n> Workperson Acorn\r\n> Director"
    assert split_body(body) == ("Thanks Workperson!", "")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_gmail.py -q`
Expected: FAIL (ImportError: `split_body`).

- [ ] **Step 3: Implement**

`archie/connectors/gmail.py`:

```python
_SIG = re.compile(r"(?m)^-- ?$")


def _unquoted(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(">")).strip()


def split_body(body: str) -> tuple[str, str]:
    """(the message, its signature), with quoted replies dropped. Line endings are made the
    same first, so stripping doesn't depend on the sender's mail client."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    m = _QUOTE_HEADER.search(body)
    if m:
        body = body[: m.start()]
    pieces = _SIG.split(body, maxsplit=1)
    main = pieces[0]
    sig = pieces[1] if len(pieces) > 1 else ""
    main = re.split(r"(?m)^-{2,}\s*Original Message\s*-{2,}", main)[0]
    return _unquoted(main), _unquoted(sig)


def clean_body(body: str) -> str:
    """Drop quoted replies and signatures so each message is indexed once."""
    return split_body(body)[0]
```

In `chunk_thread`, use `text_body, sig = split_body(m.get("body", ""))` for the message chunk, and after appending it:

```python
        if sig:
            chunks.append(Chunk(f"s{i}", path, 0, 0, sig, source=NAME, ts=m.get("date"),
                                people=[(m.get("from_email") or "").lower()],
                                label=f"Signature of {who} ({when(m.get('date'))})",
                                sender=(m.get("from_email") or "").lower()))
```

`archie/index/chunk.py`: `CHUNKER_VERSION = "3"`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_gmail.py tests/unit/test_chunk.py tests/unit/test_index.py -q`, then `uv run pytest -q`
Expected: PASS. If a vignette asserts exact packet contents that now include a signature chunk, check whether the fixture mail has a `-- ` line; fix the assertion, not the chunker.

- [ ] **Step 5: Commit**

`docs/DESIGN.md` §5.3 Email row: "one message, quoted reply text removed; the signature is its own chunk (`s{i}`)". `okf/components/connectors.md`, `okf/components/index-search.md` (chunker version 3 → reindex).

```bash
git add archie/connectors/gmail.py archie/index/chunk.py tests/unit/test_gmail.py docs/DESIGN.md okf/components/connectors.md okf/components/index-search.md
git commit -m "Email signatures are their own chunks; CRLF and LF mail strip the same"
```

Live: the next start triggers a full reindex (about a minute).

### Task 10: Titles read by code; shown in who, the model's context and briefings

**Files:**
- Create: `archie/derive/titles.py`
- Modify: `archie/ask/intents/who.py` (`person_lines`, `about`)
- Modify: `archie/derive/enrich.py` (system prompt gets the titles)
- Modify: `archie/briefings/build.py` (`_people_lines`)
- Modify: `tests/vignettes/week.py` (signature on Priya's `t_paused` mail)
- Test: `tests/unit/test_titles.py` (new), `tests/vignettes/test_m2.py`, `tests/vignettes/test_m3.py` (M)

**Interfaces:**
- Consumes: signature chunks (Task 9); `chunks_with_people` with `sender` (Task 4).
- Produces: `@dataclass Title(text: str, date: str, path: str, chunk_id: str)`; `title_from_signature(sig: str, names: set[str], org: str | None) -> str | None`; `titles(ctx, entity_id: str) -> list[Title]` (newest first, one per distinct text); `role_line(ts: list[Title]) -> str | None`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_titles.py`:

```python
from archie.derive.titles import Title, role_line, title_from_signature

NAMES = {"workperson acorn", "workperson"}


def test_title_skips_name_phone_url_and_company():
    assert title_from_signature("Workperson Acorn\nDirector of Engineering\n781-526-7220", NAMES, "overwatchdata.io") \
        == "Director of Engineering"
    assert title_from_signature("Workperson Acorn\nOverwatch Data\nVP of Engineering", NAMES, "overwatchdata.io") \
        == "VP of Engineering"


def test_no_title_gives_none():
    for sig in ("Workperson Acorn\n781-526-7220", "Sent from my iPhone", "Thanks!", "Workperson\nhttps://ow.example",
                "Workperson Acorn\nkeith@ow.example"):
        assert title_from_signature(sig, NAMES, "ow.example") is None, sig


def test_sent_from_my_phone_is_not_a_title():
    assert title_from_signature("Sent from my iPhone", set(), None) is None


def test_role_line_shows_every_title_newest_first():
    one = [Title("Director of Engineering", "2026-09-22T20:16:16+00:00", "p", "s0")]
    two = one + [Title("VP of Engineering", "2026-09-18T02:13:48+00:00", "q", "s0")]
    assert role_line(one) == "Role: Director of Engineering (signed Sep 22)"
    assert role_line(two) == "Role: signs as Director of Engineering (Sep 22) and VP of Engineering (Sep 17)"
    assert role_line([]) is None
```

(`short_date` shows local time; the test environment's timezone decides "Sep 17" vs "Sep 18" for 02:13 UTC. Pin it the way `tests/unit/test_times.py` does, or pick UTC times far from midnight if the repo doesn't pin a timezone.)

Add a rule for "Sent from my …": skip any line starting with "sent from".

`tests/vignettes/week.py`: Priya's `t_paused` body becomes `"Heads up: the auth migration is paused pending security review.\n\n-- \nPriya Sharma\nProduct Manager, Auth\nAcme"`.

`tests/vignettes/test_m2.py`:

```python
def test_B_role_comes_from_the_signature(tmp_path):
    w = Week(tmp_path)
    assert "Role: Product Manager, Auth (signed Sep 30)" in _glance(w.ask("who is Priya?"))
```

and update `test_A_standard_briefing`'s Priya assertion to `"Priya Sharma · Product Manager, Auth · last talked Thu Oct 1" in out`.

`tests/vignettes/test_m3.py` (M):

```python
def test_M_two_titles_are_both_shown(tmp_path):
    from tests.vignettes.test_m2 import _glance

    w = Week(tmp_path)
    w.add_message("t_paused", mail("p3", "t_paused", f"Priya Sharma <{PRIYA}>", f"Test Testerson <{ME}>", "Re: Auth migration",
                                   "Update soon.\n\n-- \nPriya Sharma\nSenior Product Manager", at(1, 15)), "501")
    w.ctx.now = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)
    w.sync()
    w.ctx.index.sync()
    glance = _glance(w.ask("who is Priya?"))
    assert "Role: signs as Senior Product Manager (Oct 1) and Product Manager, Auth (Sep 30)" in glance
```

(Import `mail`, `at`, `PRIYA`, `ME` from `tests.vignettes.week`, as `test_m2.py` does.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_titles.py tests/vignettes/test_m2.py tests/vignettes/test_m3.py -q`
Expected: FAIL (ImportError; no Role line).

- [ ] **Step 3: Implement**

`archie/derive/titles.py`:

```python
"""Titles from email signatures, read by code (spec: durable-fixes §3). Computed when asked,
from the person's own signature chunks; the raw mail is the source of truth."""

from __future__ import annotations

import re
from dataclasses import dataclass

from archie.ask.context import Ctx
from archie.index.chunk import short_date

_SKIP = re.compile(r"\d|@|https?://|www\.", re.I)


@dataclass
class Title:
    text: str
    date: str
    path: str
    chunk_id: str


def title_from_signature(sig: str, names: set[str], org: str | None) -> str | None:
    company = (org or "").lower().split(".")[0]
    for line in sig.splitlines():
        s = line.strip().strip("|•·-–— ").strip()
        low = s.lower()
        if not s or low.startswith("sent from") or _SKIP.search(s):
            continue
        if low in names or any(low.startswith(n + " ") or low == n for n in names if n):
            continue
        if company and low.replace(" ", "") == company:
            continue
        if 2 <= len(s.split()) <= 8 and not s.endswith(("!", "?")):
            return s
    return None


def titles(ctx: Ctx, entity_id: str) -> list[Title]:
    from archie.derive.people import PeopleDirectory, org

    d = PeopleDirectory.load(ctx.home)
    meta = d.meta.get(entity_id) or {}
    ids = d.identifiers(entity_id)
    if not ids:
        return []
    names = {str(n).lower() for n in [meta.get("name"), meta.get("full_name"), *(meta.get("aliases") or [])]
             if n and "@" not in str(n)}
    names |= {n.split(" ")[0] for n in list(names) if " " in n}
    out: dict[str, Title] = {}
    for c in ctx.index.chunks_with_people(ids, limit=100_000, before=ctx.now.isoformat()):
        if c["source"] != "gmail" or not c["chunk_id"].startswith("s") or (c.get("sender") or "") not in ids:
            continue
        t = title_from_signature(c["text"], names, org(meta))
        if t and t.lower() not in out:
            out[t.lower()] = Title(t, c["ts"] or "", c["path"], c["chunk_id"])
    return list(out.values())


def role_line(ts: list[Title]) -> str | None:
    if not ts:
        return None
    if len(ts) == 1:
        return f"Role: {ts[0].text} (signed {short_date(ts[0].date)})"
    bits = [f"{t.text} ({short_date(t.date)})" for t in ts[:3]]
    return "Role: signs as " + (", ".join(bits[:-1]) + " and " + bits[-1])
```

`archie/ask/intents/who.py`: `person_lines(directory, eid, history, facts=None, titles=None)`. Where it adds `Role:`:

```python
    if meta.get("role"):
        lines.append(f"Role: {meta['role']}")
    elif titles:
        from archie.derive.titles import role_line

        lines.append(role_line(titles))
```

Keep `Known for` shown only when there's no role and no title (`if facts and not meta.get("role") and not titles`). In `who_intent`, compute `ts = titles(ctx, eid)` once, pass it to `person_lines`, and extend `about`:

```python
    if ts:
        about += " Their email signatures say: " + "; ".join(f"{t.text} (signed {short_date(t.date)})" for t in ts) \
                 + ". If they differ, give both with dates; don't pick one."
```

`archie/derive/enrich.py`: after building `system`, append the same signature sentence when `titles(ctx, eid)` isn't empty.

`archie/briefings/build.py` `_people_lines`:

```python
        if meta.get("role"):
            bits.append(meta["role"])
        else:
            from archie.derive.titles import titles

            ts = titles(ctx, eid)
            if ts:
                bits.append(ts[0].text + (f" (also signed as {ts[1].text})" if len(ts) > 1 else ""))
            elif facts:
                bits.append(facts[0]["text"])
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_titles.py tests/unit/test_who.py tests/unit/test_briefings.py tests/vignettes -q`, then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

`docs/VIGNETTES.md`: B's Coverage note drops "no role from signatures" (row stays 🟨 for "Priya S."). `docs/DESIGN.md` §4.2: `role` is the user's; without one, "Role:" shows signature titles with dates (two titles shown side by side). `okf/components/derivers.md` (`titles.py`), `okf/components/ask.md`, `okf/components/briefings.md`, `okf/log.md`.

```bash
git add archie/derive/titles.py archie/ask/intents/who.py archie/derive/enrich.py archie/briefings/build.py tests/vignettes/week.py tests/unit/test_titles.py tests/vignettes/test_m2.py tests/vignettes/test_m3.py docs/VIGNETTES.md docs/DESIGN.md okf/components/derivers.md okf/components/ask.md okf/components/briefings.md okf/log.md
git commit -m "Titles from signatures: Role line, model context and briefings; two titles both shown"
```

Live check (about 2¢): `archie ask "What is Workpersons title?"` names both "Director of Engineering (Sep 22)" and "VP of Engineering (Sep 17)", cited; `archie ask "tell me about Workperson"` shows the Role line.

## Step 6 — Review loop (spec §5b, §5c)

### Task 11: Eval questions outside the repo; phrasing variants; REVIEW.md step

**Files:**
- Modify: `scripts/prompt_eval.py` (load `~/.archie/reviews/evals/questions.yaml` after `QUESTIONS`)
- Create: `tests/vignettes/variants.py`
- Modify: `tests/vignettes/test_m2.py` (B and J questions through `variants`)
- Modify: `docs/REVIEW.md` (§5 new step; §7 "Since last review" runs the eval)
- Test: `tests/unit/test_prompt_eval.py` (new), `tests/vignettes/test_m2.py`

**Interfaces:**
- Produces: `prompt_eval.load_questions(home: Path) -> list[dict]`; `variants(question: str) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_prompt_eval.py`:

```python
import importlib.util
from pathlib import Path


def _module():
    spec = importlib.util.spec_from_file_location("prompt_eval", Path("scripts/prompt_eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_review_questions_are_loaded_after_the_built_in_ones(tmp_path):
    mod = _module()
    (tmp_path / "reviews/evals").mkdir(parents=True)
    (tmp_path / "reviews/evals/questions.yaml").write_text(
        "- q: What is Workpersons title?\n  handlers: [who]\n  has: [Director of Engineering]\n  lacks: []\n")
    qs = mod.load_questions(tmp_path)
    assert qs[: len(mod.QUESTIONS)] == mod.QUESTIONS
    assert qs[-1]["q"] == "What is Workpersons title?"
    assert mod.load_questions(tmp_path / "missing") == mod.QUESTIONS
```

`tests/vignettes/variants.py`:

```python
"""The same question in the ways people really type it (spec: durable-fixes §5c)."""

import re


def variants(question: str) -> list[str]:
    out = [question, question.lower(), re.sub(r"[?.!]+$", "", question)]
    m = re.search(r"\b([A-Z][a-z]+)'s\b", question)
    if m:
        out.append(question.replace(f"{m.group(1)}'s", f"{m.group(1)}s"))
    return list(dict.fromkeys(out))
```

`tests/vignettes/test_m2.py`, replace the loop in `test_B_possessive_question_finds_the_person` and add a J variant test:

```python
from tests.vignettes.variants import variants


def test_B_questions_in_every_phrasing(tmp_path):
    w = Week(tmp_path)
    for base in ("who is Priya?", "what is Priya's role?"):
        for q in variants(base):
            assert _glance(w.ask(q)).splitlines()[1].strip() == "Priya Sharma", q


def test_J_history_in_every_phrasing(tmp_path):
    w = Week(tmp_path)
    for q in variants("what's my history with Ken?"):
        assert _glance(w.ask(q)).splitlines()[1].strip() == "Ken Ito", q
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_prompt_eval.py tests/vignettes/test_m2.py -q -k "review_questions or every_phrasing"`
Expected: FAIL (`load_questions` missing, `variants` missing).

- [ ] **Step 3: Implement**

`scripts/prompt_eval.py`:

```python
def load_questions(home: Path) -> list[dict]:
    """The built-in questions, then the ones reviews added (real words, never committed)."""
    import yaml

    extra = home / "reviews/evals/questions.yaml"
    added = (yaml.safe_load(extra.read_text()) or []) if extra.exists() else []
    return QUESTIONS + [q for q in added if isinstance(q, dict) and q.get("q")]
```

In `main`, replace `enumerate(QUESTIONS, 1)` with `enumerate(load_questions(Path.home() / ".archie"), 1)` (use the real home the script copies from, if it has a variable for it).

`docs/REVIEW.md` §5, add after the three bullets:

```markdown
- **turn it into tests:** add the ask to `~/.archie/reviews/evals/questions.yaml` (`q`, `handlers`, `has`,
  `lacks`, as in `scripts/prompt_eval.py`); never to the repo. In the suggested fix, describe the fictional
  fixture that reproduces it (for example "a person with 15 newer copied-on passages and one older signed
  email"), so the fix's vignette test covers what the live data had.
```

and in §7 item 7 ("Since last review"): "Run `uv run python scripts/prompt_eval.py --label review` and report which earlier failures still fail."

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_prompt_eval.py tests/vignettes -q`, then `uv run pytest -q`
Expected: PASS. If a variant fails, the fix belongs in the code under test (normalizer, `names_in`, `resolve`), not in `variants`.

- [ ] **Step 5: Commit**

`okf/log.md` (review loop). Create `~/.archie/reviews/evals/questions.yaml` on the real home with the fifth review's asks ("What is Workpersons title?" → `who`, has `Director of Engineering|VP of Engineering`; "Tell me about Acorn" → `who`, has `energy`). That file is under `~/.archie` and is **not** committed.

```bash
git add scripts/prompt_eval.py tests/vignettes/variants.py tests/vignettes/test_m2.py tests/unit/test_prompt_eval.py docs/REVIEW.md okf/log.md
git commit -m "Reviews turn failures into tests: eval questions outside the repo, phrasing variants"
```

### Task 12: Live check and wrap-up

**Files:**
- Modify: `docs/superpowers/specs/2026-10-04-durable-fixes-design.md` (status line; "Added while building" notes if anything changed)
- Modify: `docs/VIGNETTES.md` (Coverage), `okf/log.md`

- [ ] **Step 1: Full suite and OKF**

Run: `uv run pytest -q` and `python3 scripts/okf_check.py`
Expected: all green, no OKF errors.

- [ ] **Step 2: Live checks on the real home** (about 5¢ in all, beyond the one-off ~$0.30 dossier rebuild)

Run one sync, then:
- `uv run archie ask "What is Workpersons title?"` → names Workperson; both titles with dates, cited.
- `uv run archie ask "tell me about Acorn"` → includes "full of energy…"; "At a glance" shows "Acorn (Acorn Testerson)".
- `uv run archie ask "Tell me about Goodspouse and CPS"` → cites her Sep 28 email.
- `uv run archie ask "who is Priyaa?"` → "I didn't recognise anyone called Priyaa, so I searched everything instead." (or the nothing-found line).
- Check the last `logs/usage.jsonl` lines have `people`, `topic`, `sources`.

- [ ] **Step 3: Record and commit**

Spec status → "built 2026-10-xx". `okf/log.md` entry with the live results (quote Archie's replies the way earlier entries do, no real mail beyond what earlier entries already quote).

```bash
git add docs/superpowers/specs/2026-10-04-durable-fixes-design.md docs/VIGNETTES.md okf/log.md
git commit -m "Fixes that last: built and checked live"
```

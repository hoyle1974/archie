# Fixes that last: design

**Status:** built 2026-10-04 and checked live (see `okf/log.md`). Drafted the same day from the fifth usage review.
**Date:** 2026-10-04
**Builds on:** [Understand first](2026-10-03-understand-first-design.md)

## Goal

Reviews keep finding problems that a one-off fix to the data would hide. The user wants
Archie itself to stop producing them. The fifth review's failures look like four bugs but
come from three habits, plus a gap in how reviews feed back into tests:

1. **Derived things are computed once.** A telling is applied when it's said and never
   again. Acorn's "full of energy and 3 and a half" and the full names for Acorn and Childone
   were said before the fixes that handle them, so they're still missing. A people-facts
   rebuild starts from an empty list and reads only the person's 12 newest passages, so a
   prompt change quietly drops older facts.
2. **Each part of Archie picks its own evidence.** Building a people file reads the 12
   newest passages (Workperson's two signed emails are #21 and #24, so his file has no facts).
   `who` reads the 40 newest and ignores the topic. Search fuses three rankings (it missed
   "Goodspouse and CPS" the first time).
3. **Code and model meet at brittle exact-word checks, and fallbacks guess.** "What is
   Workpersons title?" lost Workperson because the check that guards against invented names needs
   "workperson" as a whole word, and "workpersons" / "workperson's" aren't. `who` then used the topic
   ("title") as a name.
4. **Review findings don't become tests.** Each review finds failures by hand, and nothing
   stops them coming back.

Separately, titles in email signatures never reach a person's "Role:" line. Roles come only
from what the user tells Archie. And the gmail chunker strips signatures from mail with
LF line endings but keeps them for CRLF mail (`^-- ?$` doesn't match `-- \r`), so whether a
title can be cited depends on the sender's mail client.

This design covers five changes. Targets: vignette B's new acceptance criteria (possessive
questions, titles from signatures), M (two titles shown, neither picked), N (tellings
reach the person's file even if said before a fix), and J/B (a topic in a person question).

## Constraints (unchanged)

- Files under `~/.archie/` are the source of truth; SQLite is a rebuildable index. Nothing
  here stores a fact only in the DB. Titles are read from raw mail; versions and replay
  state are YAML under `state/`.
- In derived Markdown, Archie writes only inside `<!-- archie:auto -->` fences.
- The model's factual claims carry `{file, chunk, quote}` and the verifier drops anything
  not verbatim in the cited chunk. Counts, dates and titles from signatures come from code.
- The user's own words are never checked against the archive.
- Read-only toward the world. No new commands; maintenance stays under `archie admin`.
- Answers open with a plain-English summary; IDs and paths never lead.

## 1. Re-derive when the logic improves

**Rule:** every derivation that depends on a prompt or on code that can change records the
version that produced it. When the version changes, it's redone from the files on the next
sync, without the user doing anything.

### 1a. A shared version stamp

`archie/derive/versions.py`:

```python
def stamp(name: str, *parts: str) -> str:
    """12-char hash of a deriver's prompt(s), reply shape and code version constant."""
```

`enrich.prompt_version()` becomes `stamp("people_facts", INSTRUCTIONS_VERSION, prompt,
repr(SHAPE))`. Tellings use `stamp("remember", REMEMBER_VERSION, prompt, repr(SHAPE))`.

### 1b. People-facts rebuilds read all of the person's material

Today a fresh rebuild (`fresh` or `facts_stale`) clears the facts and reads 12 passages.
Instead it reads everything about the person through the evidence selector (§2), in
batches of at most `people.facts_max_chars` (default 40,000 characters), oldest batch first.
Facts accumulate across batches with the existing dedupe, and the newest 8 are kept, as
today. Most people fit in one batch (Workperson: 24 passages, about 10,000 characters; Goodspouse:
23, about 20,000).

Incremental runs (new mail since last time) are unchanged except that they also use the
selector, limited to passages newer than `since`.

### 1c. Tellings are re-applied when the remember logic changes

`journal/told.md` keeps the user's words; it isn't changed. A new file
`state/told_applied.yaml` records, per told line (keyed by a hash of its date and text),
the remember version that last applied it.

A post-index step, `replay_tellings` (before `enrich_people` in
`archie/derive/registry.py`), runs on each sync:

- Candidates: lines whose result is `saved only` or starts with `remembered:`, whose
  recorded version differs from the current one (or is missing).
- Each is run, **in told order**, through `remember_people(ctx, text)`, one fast model call
  each. Order matters: a later correction is applied after the earlier statement, so it
  still wins.
- `remember` is already idempotent: a note that's already there isn't added twice, and the
  frontmatter keys get the same values. A line where the model finds no person does nothing.
- Ignore and un-ignore lines are never replayed (their effect lives in `config.yaml`), and
  neither is news that could close an item: closing an item later, on old news, could close
  the wrong one.
- The sync report says what changed: "Re-applied 2 things you told me earlier: Acorn
  (Acorn Testerson), Childone (Childone Rook Strohm)." Lines that changed nothing aren't
  mentioned.
- The model budget applies as to any call. A failed call leaves the line's version
  unchanged, so it's retried next sync (and counted by `failures.py` like other derivers).

The first run after this ships replays every person telling once (about ten lines today,
under 1¢).

### 1d. Out of scope: loops

Loop extraction (`state/loops_seen.yaml`) is not replayed on a prompt change. Reprocessing
old mail could reopen items the user dismissed or closed. Loops record their version in
`loops_seen.yaml` so a later design can decide, and `archie doctor` reports how many
threads were read by an older version.

## 2. One way to gather evidence about a person

`archie/ask/evidence.py`:

```python
def person_evidence(ctx, entity_id, *, topic=None, max_items, max_chars, since=None) -> list[dict]:
    """Chunks about one person, best first, that fit the budget."""
```

Order:

1. With a topic: the person's chunks ranked by the topic (the existing hybrid `search` with
   `people=` that person's identifiers), best first.
2. Then the person's chunks they **sent** (`sender` is one of their addresses), newest first.
3. Then the rest of their chunks (to or copied), newest first.

Duplicates are skipped; a chunk too big for the remaining room is skipped, not the rest
(as `search._fit` does). Dossiers, loops and briefings are left out, as enrichment does
today. `before=ctx.now` drops future meetings.

Callers:

- **`who`** (`archie/ask/intents/who.py`): the person's dossier still goes in first, as
  now; the selector replaces the newest-first loop after it. Passes the
  understanding call's `topic` when there is one, so "Tell me about Goodspouse and CPS" puts
  the CPS email first however many passages Goodspouse has. "Recent" stays code-computed
  newest-first, as now.
- **Enrichment** (§1b): no topic; the person's own messages come first, so a signature or a
  self-description isn't buried behind threads they were only copied on.
- **Briefings** (per-attendee context): same call, no topic.
- **Search** keeps its fused ranking; its person-filtered try already does step 1.

## 3. Titles from signatures, by code

### 3a. Signatures become their own chunks

`clean_body` in `archie/connectors/gmail.py` normalizes line endings first (`\r\n` → `\n`),
so stripping is the same for every mail client. The signature it cuts off (from the `-- `
line to the end, before quoted text) becomes a separate chunk per message:

- `chunk_id` `s{i}` (message chunk ids `c{i}` don't change), `source` gmail,
  `ts`/`sender` as the message, `people` = the sender only.
- `label`: "Signature of Workperson Acorn (Sep 22)".

`CHUNKER_VERSION` goes to 3, which triggers a full reindex (about a minute for the current
home). Message chunks get a little shorter for CRLF mail, and the signature is still
quotable, so citations stay verifiable.

### 3b. Reading a title

`archie/derive/titles.py` (code only, no model):

```python
def titles(ctx, entity_id) -> list[Title]:  # Title(text, date, path, chunk_id)
```

For each signature chunk the person sent: drop the line that is their name, phone numbers,
addresses, URLs and emails. The title is the first remaining line of 2–8 words, with no
digits, that isn't their company name alone. Titles are kept per distinct text with their
newest date, newest first. Computed when asked, from the index (like "Recent"), not stored:
the raw mail is the source of truth.

### 3c. Showing it

- **`who` "At a glance":** with no user-set `role`, one line:
  - one title: `Role: Director of Engineering (signed Sep 22)`
  - two or more: `Role: signs as Director of Engineering (Sep 22) and VP of Engineering
    (Sep 17)` — both shown, neither picked, as vignette M requires.
  A role the user set still wins and is shown alone.
- **The model's context** (`about` in `who`, `describe` for enrichment) includes the same
  titles with dates, so "what is Workperson's title?" gets a cited answer naming both.
- **Briefings** show the newest title beside the person, with "(also signed as …)" when
  titles differ.

## 4. Names matched by code, the same way everywhere

### 4a. One normalizer

`archie/names.py`:

```python
def name_key(word: str) -> str:
    """lower case, curly quotes straightened, edge punctuation and a trailing 's / ' / s dropped."""
def name_forms(word: str) -> set[str]:  # {"workpersons"} -> {"workpersons", "workperson"}
```

Used by:

- `_words` / `_said` / `_grounded` in `archie/ask/understand.py`: each word heard adds its
  `name_forms`, so "Workpersons" and "Workperson's" ground "Workperson". (The added forms only widen what
  counts as said; they never add a name the user didn't type.)
- `PeopleDirectory.find`: the query is tried as given, then by `name_key`.
- `PeopleDirectory.mentioned_in` / `_named`: a name may be followed by `'s`, `’s` or `s'`.
  The rules that "a name inside someone's longer name doesn't count" and "a one-word name
  must be capitalized" stay.

### 4b. Code finds known people in the message

`PeopleDirectory.names_in(message) -> list[str]`: entity ids whose name, alias or first name
(3+ letters) appears in the message as a whole word, possessive allowed, case-insensitive.
After the understanding call, if a `question` part has intent `who` and no people survived
grounding, the people code found in the message are used instead. Matching is
case-insensitive here ("tell me about goodspouse") because it only runs for a `who` question
that has lost its person; elsewhere a one-word name must still be capitalized, so "a
acorn" is nobody.

### 4c. `who` never treats a topic as a name

In `resolve` (`who.py`), the query is a person from `people`, or a name taken from the
message ("who is X", or 4b). The topic is never used as a name.

When no known person resolves (after the normalizer and the code scan in 4b), `who` never
stops at "I don't know anyone called …". It hands the user's original question to the
search intent with the same parameters, so hybrid retrieval (FTS and vector) still runs.
For "What is Workpersons title?" today, no search ran at all. The answer says plainly what
happened before what search found:

- a name was in the message: "I didn't recognise anyone called Dana, so I searched
  everything instead." then search's cited answer;
- no name was found: "I couldn't tell who you meant, so I searched everything instead."
  then search's cited answer;
- search finds nothing either: "I didn't recognise anyone called Dana, and a search found
  nothing about it."

These opening lines are written by code, not the model.

## 5. Every review failure becomes a test

### 5a. The usage log shows what Archie understood and read

`logs/usage.jsonl` part entries gain `people` and `topic` (from `Part.params`). Answers
built from a packet add `sources`: the `path#chunk` of every source sent to the model, in
order (`Answer.sources`, filled by `synthesize`). A review can then tell "the answer wasn't
in what the model saw" from "the model missed it" without re-running anything.

### 5b. Reviews turn failures into tests

`docs/REVIEW.md` §5 gains a step. For each failure a fix is suggested for, the review
also writes:

- **an eval case** in `~/.archie/reviews/evals/questions.yaml` (real words, never
  committed): the question, the expected handler, and words the answer must and must not
  contain. `scripts/prompt_eval.py` loads these after its built-in list.
- **the shape of a vignette test**, in the suggested fix: the fictional fixture that
  reproduces it (for example "a person with 15 newer copied-on passages and one older
  signed email"), so the fix's test covers what the live data had.

The review's "Since last review" section runs the eval and reports which earlier failures
still fail.

### 5c. Phrasing variants in vignette tests

`tests/vignettes/variants.py`: `variants("who is Priya?")` gives the question lowercase,
without punctuation, and with a possessive where a name is followed by a noun ("what is
Priya's role?" → "what is Priyas role?"). Vignettes B and J run their questions through
it; each variant must reach the same handler and person.

## Testing

| Change | Test |
|---|---|
| 1b rebuild reads everything | `test_enrich.py`: a person with 30 passages and an old fact-bearing one; a forced rebuild keeps that fact. |
| 1c replay | `test_tell.py` / new `test_replay.py`: a "saved only" line about Acorn gets into his notes after a version bump; a later correction still wins; ignore lines aren't replayed; a second sync makes no calls. Vignette N: a telling saved before a version bump reaches the person's file. |
| 2 evidence | new `test_evidence.py`: topic first, then sent, then the rest; budget respected. Vignette B/J: a person with 50 passages and the topic in the oldest. |
| 3 signatures | `test_gmail.py`: CRLF and LF mail strip the same; the signature is chunk `s{i}`. New `test_titles.py`: name, phone and URL lines dropped; two titles newest first. Vignette B: "Role:" from a signature; vignette M: two titles both shown. |
| 4 names | `test_understand.py`: "What is Workpersons title?" and "What is Workperson's title?" keep Workperson. `test_people.py`: `find("Workperson's")`, `mentioned_in("Workperson's laptop")`. `test_who.py`: no person → search, never "anyone called title"; search finding nothing says so. Vignette B: a misspelled or unknown name ("who is Priyaa?", "what is Zed's role?") gets "I didn't recognise anyone called …" and an answer from search, never a topic word treated as a name. |
| 5 logging | `test_ask.py`: a usage line has `people`, `topic` and `sources`. |

Vignette B's Coverage note ("no role from signatures") clears when its new criteria pass.

## Build order

Each step is its own commit and leaves every test passing.

1. **Names** (§4). Small, and it fixes a live failure.
2. **Usage log** (§5a). Makes every later live check exact.
3. **Evidence selector** (§2), adopted by `who`.
4. **Re-derivation** (§1): version stamps, rebuilds through the selector, telling replay.
5. **Signatures and titles** (§3), with the reindex.
6. **Review loop** (§5b, §5c): `REVIEW.md`, eval questions file, phrasing variants.

After each step: update the OKF bundle and `okf/log.md`, run a live check on the real home
(the matching question from the fifth review), and update the vignette Coverage table.

## Decisions for the user

Made by default in this draft, since they weren't discussed:

1. **Replay scope (§1c):** only person tellings ("saved only" and "remembered") are
   replayed, never news that could close an item or ignore lines.
2. **`told.md` stays untouched** by replays. What changed is said in the sync report and
   recorded in `state/told_applied.yaml`, not by rewriting the "→ result" on old lines.
3. **Titles are computed at question time** from signature chunks, not stored in the
   dossier (like "Recent"). The alternative is a code-written "Titles" list inside the
   dossier fence, which the user could read in the file.
4. **Real eval questions move out of the repo** going forward (`~/.archie/reviews/evals/
   questions.yaml`). The 14 already in `scripts/prompt_eval.py` stay where they are unless
   the user wants them moved too.
5. **Loops aren't replayed** (§1d).

## Added while building

- **The user's typed name beats the model's completion (§4c).** Live, "Tell me about Acorn"
  after two questions about Workperson Acorn was rewritten by the understanding call to "Tell me
  about Workperson Acorn", and `who` answered about Workperson although Acorn (the user's son) is a
  known person. `resolve` now checks the words the user typed (passed to handlers as
  `params["said"]`): if they are someone's whole name or alias, that person wins. A typed
  first name the model completed ("Priya" to "Priya Sharma") still resolves as before.
  Test: `test_who.py::test_a_whole_name_the_user_said_beats_the_models_completion`.
- **`REVIEW.md` ground rule (§5b).** "Write one file only" now also allows appending asks to
  `reviews/evals/questions.yaml` and the eval run's results, which the new steps need.

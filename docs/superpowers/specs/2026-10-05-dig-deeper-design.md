# Dig deeper when an answer doesn't help: design

**Status:** approved in conversation 2026-10-05; waiting on spec review. No code yet.
**Date:** 2026-10-05
**Builds on:** [Understand first, then act](2026-10-03-understand-first-design.md)

## Goal

When the user asks about something, it is almost always important to them and almost
always mentioned somewhere in their data. Archie should work to find it, not stop at the
first intent's dead end.

The case that prompted this (usage log, 2026-10-06 05:39–05:46 UTC):

1. "I will meet with Workpersontwo next week" was saved as `other->gap`.
2. "Can you prep me for that meeting" was understood correctly (`brief`, people
   `["Workpersontwo"]`, resolved to "…the meeting with Workpersontwo next week?"). Then `brief` found
   no one called Workpersontwo in the people directory, **threw away** the sentence "I don't know
   anyone called Workpersontwo.", fell through to the meeting picker with no topic, found only
   personal events (which get no prep), and answered "You have no meetings to prepare for
   in the next two weeks." No model wrote that answer.
3. "Tell me about Workpersontwo" found her: `who` falls back to search when a name is unknown,
   and the answer cited a Sep 23 meeting and Workperson's "Thanks for pinging Workpersontwo!".

Workpersontwo has no dossier because she has never appeared with her own email address: only
as the display name on a Koalendar notification (bulk, role account), in calendar titles
with no attendees, and in the text of other people's mail. Dossiers are created only from
correspondence (DESIGN §4.2), so no rule was broken; the rules just stopped short of
helping.

The user chose four behaviors:

- **Notice unhelpful answers**, both where code knows it hit a dead end and by asking a
  fast model whether the answer addressed the question.
- **Dig with an agent loop**: several rounds of looking, each step chosen by the model and
  carried out by code.
- **Look on the web too**, for public context, with web facts cited and verified like any
  other.
- **Offer to start a file on someone mentioned but unknown**, and create it only on yes.

## Principles kept

- Every fact shown is cited and verified verbatim against a file (§2.5). The dig loop
  ends in the existing `synthesize` and verifier; nothing it gathers skips them.
- Files are the source of truth (§2.1): fetched web pages are saved under
  `sources/web/` before anything cites them.
- The model has no tools (§9). Archie is the tool: the model picks one action per round
  from a fixed read-only menu and code runs it.
- Read-only toward the world (§2.8): the only new outside reads are web searches and page
  fetches. Nothing is sent or posted.
- Counts and dates come from code. The "I looked further" line, the offer and the
  confirmation are written by code.

## 1. Noticing an unhelpful answer

### 1.1 Dead ends (code)

`Answer` gains `dead_end: str | None`, a short reason in plain words. Intents set it where
they now give up on something the user named or asked about:

| Where | `dead_end` |
|---|---|
| `brief`: named people, none known | `"no file on anyone called Workpersontwo"` |
| `brief`: no matching meeting and nothing upcoming | `"no meeting matched"` |
| `who`: unknown person and the search fallback found nothing | `"no one called X, and search found nothing"` |
| `search`: no hits | `"search found nothing"` |
| any intent: the model cited points but the verifier dropped all of them | `"every cited point was dropped"` |

Correct empty results are not dead ends: "You have nothing open that matches. Nice.", an
empty agenda, "I don't have any open questions for you."

**`brief` fix (independent of the rest).** When names were given and none resolved,
`brief` no longer falls through to the meeting picker. It sets `dead_end` and keeps the
`said` sentences ("I don't know anyone called Workpersontwo.") so they are shown, as Vignette V's
acceptance already requires. Without digging (budget spent, `ask.dig.enabled: false`) the
reply is those sentences plus the existing "Which meeting?"/"no meetings" text.

### 1.2 The answer check (fast model)

After `_respond` builds the answer, one fast-tier call with a new shape `answer_check`:

```
helpful: no
missing: the user wanted prep for a meeting with Workpersontwo; the answer only says the calendar is empty
```

Its input: the message, the resolved question, the last exchange's summary, and the answer
as rendered for the user (no sources). About 1–2k tokens, ~$0.002, ~1 s.

Skipped when any of these hold:

- the reply came from a code-only path (`quick_route`, "show N", a "which one?" reply,
  "really?", a yes/no to an open question);
- no part is a `question` (tellings, instructions and answers are acted on, not answered);
- the answer already has a `dead_end`;
- the monthly budget is spent, or `ask.dig.enabled` is false;
- the answer is a pending "which one?" question.

### 1.3 Handoff

If `dead_end` is set or the check says `helpful: no`, the question part goes to the dig
loop with the reason as its starting hint and the first answer's packet as its starting
evidence. A mixed message only digs its question parts; tellings in it are applied as
before.

- If the dig produces an answer with at least one verified claim, it replaces the first
  answer.
- Otherwise the first answer is shown with one line added by code:
  "I looked further (5 searches, 2 web pages) and found nothing more."

### 1.4 Usage log

`logs/usage.jsonl` entries gain `check` (`"helpful"`, `"unhelpful"` or absent when
skipped), `dead_end`, and `dig`: `{"rounds": n, "actions": [...], "improved": bool,
"usd": x, "offered": "Workpersontwo Birch" | null}`.

## 2. The dig loop (`archie/ask/dig.py`)

```python
def dig(ctx: Ctx, question: str, hint: str, start: Packet, recent: list[dict],
        progress: Callable[[str], None] | None = None) -> DigResult: ...

@dataclass
class DigResult:
    answer: Answer | None   # None: nothing verified
    actions: list[str]      # "search: Workpersontwo Birch", …
    new_person: str | None  # checked by code (§4.1)
    usd: float
```

### 2.1 A round

One fast-tier call with a new shape `dig_step`:

```
why: the calendar titles mention "Workpersontwo Birch"; search the full name
do: search
arg: Workpersontwo Birch
```

Final round form:

```
why: the Sep 23 meeting and Workperson's thanks are enough
do: answer
new_person: Workpersontwo Birch
```

System prompt (`archie/llm/prompts/dig_step.md`): the menu, the rules for web queries
(§3.3), "choose the single most useful next step", "stop as soon as the notebook answers
the question". User message: now line, the question, the hint, people context (as in
`synthesize`), and the **notebook**.

The notebook is written by code: each earlier step's `why`/`do`/`arg` and its result. A
result lists numbered excerpts (`[n] label: first 300 characters`) whose numbers are the
shared packet's numbers, so the model can point at what it has seen.

### 2.2 The menu

| `do` | `arg` | Code runs | Result in the notebook |
|---|---|---|---|
| `search` | a query | `search.find()` over the index (ignored senders skipped) | top 8 hits |
| `open` | a path from an earlier result | `ctx.index.chunks_of(path)`; only paths already shown in the notebook or under `people/`, `meetings/`, `loops/`, `projects/`, `journal/` | its chunks, up to 12k characters |
| `person` | a name | `PeopleDirectory.find`, then `loose=True`, then `near` | matches with name, aliases and org, or "no file on anyone called X" |
| `calendar` | `YYYY-MM-DD YYYY-MM-DD` | `load_meetings`, in range, **including** personal events and cancelled ones (marked) | one line each: local time, title, attendees by name |
| `web` | a query | §3 | the saved pages' excerpts |
| `answer` | — | ends the loop | — |

Every chunk a step returns is added to one shared `Packet`, within `ask.max_sources` and
`ask.max_source_chars` (oldest-added low-score items make room first).

An unreadable reply, an unknown `do`, an invalid `arg`, or a step repeated exactly gets
"(refused: …)" in the notebook and still counts as a round.

### 2.3 Limits

- `ask.dig.rounds` (default 5): rounds before code stops and answers.
- `ask.dig.max_usd` (default 0.25): before each call, the cost so far (from the budget
  log entries this dig wrote) plus a high estimate of the next call must stay under it;
  otherwise the loop stops and answers.
- The monthly budget applies as everywhere.
- An `LLMError` stops the loop; it answers from what it has, or returns `answer=None`.

### 2.4 Finishing

`synthesize(ctx, question, packet, DIG_INSTRUCTIONS, extra_context=hint)` on the strong
tier, so the verifier runs unchanged. `DIG_INSTRUCTIONS`: answer what the user wanted (the
hint says what the first answer missed); say which facts come from a web page.

Code appends a note: "I looked further: 3 searches, 1 calendar check, 1 web search."
(counts from `actions`, only kinds that ran). The summary still leads.

### 2.5 Progress

`dig` calls `progress("Looking further… searching “Workpersontwo Birch”")` before each action.
The TUI's Ask pane shows the latest line while it waits; the CLI writes them to stderr so
stdout stays the answer.

Typical cost: ~4 fast rounds plus one strong answer, about $0.04–0.08 and 10–25 s.

## 3. The `web` action

### 3.1 Finding links: Gemini with Google Search grounding

A new backend method, separate from `complete()`:

```python
def web_links(self, query: str, n: int = 3) -> list[dict]:  # [{"url", "title"}]
```

`GeminiBackend.web_links` makes one fast-tier call with the Google Search tool enabled,
reads only the grounding metadata's sources, follows each redirect link to its real URL,
and returns the first `n` distinct ones. The model's text is discarded. The call is
recorded in the budget log as `call: "web_links"` (tokens plus the per-query grounding
fee, added to `PRICES` as its own entry). `FakeBackend` and the heuristic test backend
return canned links.

This is the one place a model call has a tool, and its output is only a list of URLs that
code then fetches and checks; §9 says so explicitly.

### 3.2 Fetching and saving (`archie/connectors/web.py`)

For each link: HTTPS only, 10 s timeout, 2 MB cap, `text/html` or `text/plain` only, no
cookies, a plain Archie user agent. HTML becomes text with the Gmail connector's
HTML-to-text function (moved to a shared helper). A page whose text is under 200
characters is skipped.

Saved as `sources/web/<sha1(url)>.json`:

```json
{"url": "https://…", "title": "…", "fetched_at": "2026-10-06T05:55:00Z",
 "query": "Workpersontwo Birch", "text": "…"}
```

A URL fetched in the last 7 days is reused from its file. The file is indexed right away
(the dig needs its chunks now), with source `web` and label
`Web: <title> (fetched Oct 5)`. Pages are kept like every source (§2.9).

### 3.3 Query rules

The prompt says: a web query is names, organisations and topics only; never text,
addresses or numbers from the user's messages. Code refuses a query with `@`, `://`, a
digit run of 5 or more, or more than 8 words.

### 3.4 How web facts read

They are cited like any claim; the `Web:` label shows in the sources list, and
`DIG_INSTRUCTIONS` asks the model to say "according to a web page" for them rather than
stating them as the user's own mail.

### 3.5 Switch

`ask.dig.web` (default true). When false, `web` is not on the menu.

## 4. Offering to start a file

### 4.1 When

After a dig, a candidate name is, in order:

1. a name in the question part's `people` that the directory doesn't know, or
2. the dig's `new_person`.

Code accepts it only if the exact name (whole words, any case) appears in at least 2
different source files in the final packet, and it is not the user (`me.yaml`), not an
ignored sender's name, not a role account's display name, has no `(via …)` service suffix
left after stripping, and is not in `state/people_declined.yaml`. One offer per answer at
most.

The offer uses the fullest form seen ("Workpersontwo Birch" beats "Workpersontwo") and is appended
by code:

```
I don't have a file on Workpersontwo Birch yet. The name is in 5 of your sources. Want me to start one?
```

No pronoun: the user hasn't given one.

### 4.2 The pending offer

The answer carries `pending = {"kind": "offer_person", "name": "Workpersontwo Birch",
"aliases": ["Workpersontwo"], "sources": [paths], "options": []}`. In `_respond`, before
`which.match` (whose filler words include "yes"), a pending `offer_person` is answered by a
code-only yes/no match on the whole message: yes, yeah, yep, sure, ok, okay, please, do it,
go ahead, start one; no, nope, don't, no thanks, skip. Anything else drops the offer, as
with every pending question; so do 30 quiet minutes.

### 4.3 Yes

Creates `people/workpersontwo_birch.md` (`PeopleDirectory.new_id` slug rules):

```yaml
entity_id: workpersontwo_birch
name: Workpersontwo Birch
aliases: ["Workpersontwo"]
status: stub
origin: mentioned
first_seen: 2026-09-22T20:11:00Z   # earliest source that names them
last_interaction: null
```

with the usual `## My notes` and fence. Any email address that appears next to the name in
a message header in those sources ("Workpersontwo Birch <p@x.com>", not a role account or
`(via …)` sender) is added as an alias, so later mail matches the usual exact way. Then
`_enrich_one` runs for this person (`fresh=True`) and the reply, written by code, says:
"Started a file on Workpersontwo Birch with 3 facts from your mail and calendar." (or "…; I
couldn't confirm any facts yet." when none verified).

The yes is saved in `journal/told.md` with the result (`remembered: started file
workpersontwo_birch`), like other tellings.

### 4.4 No

The name is added to `state/people_declined.yaml` and never offered again. The reply:
"OK, I won't keep a file on Workpersontwo Birch." A later explicit "start a file on Workpersontwo"
is a new `start_person` action that runs the same search and creation without the 2-source
minimum (it still needs at least 1) and removes the name from the declined list.

### 4.5 Evidence for mentioned people

`PeopleDirectory.identifiers` and `ask/evidence.person_evidence` find a person's chunks by
email and handle. For `origin: mentioned` people they also match whole-word, any-case
mentions of the full `name` and of multi-word aliases. A single word is never used ("Workpersontwo"
alone could be anyone). Once the person has an email alias, both kinds count.

Two people are still never merged by name: if a correspondence dossier with the same name
appears later, the existing duplicate audit asks.

## 5. Config

```yaml
ask:
  dig:
    enabled: true
    rounds: 5
    max_usd: 0.25
    web: true
```

Defaults in `archie/config.py`.

## 6. Tests

### 6.1 Vignette W: Someone I only mentioned (`tests/vignettes/test_w_mentioned.py`)

Fixtures shaped like the real case:

- Koalendar confirmation from "Workpersontwo Birch (via Koalendar)"
  `<notifications@koalendar.com>`, bulk, `CATEGORY_UPDATES`, Sep 22.
- The user's self-sent "Updated video conference: Test Testerson & Workpersontwo Birch".
- Workperson Acorn's thread with "Thanks for pinging Workpersontwo!" (Oct 1).
- Calendar event "Test Testerson & Workpersontwo Birch", Sep 23, no attendees.
- Personal events only in the next two weeks.

Steps and checks:

1. "I will meet with Workpersontwo next week", then "Can you prep me for that meeting".
   The answer has verified claims citing the Sep 23 meeting and Workperson's thread, never says
   "no meetings", and ends with the offer naming Workpersontwo Birch.
2. "yes" creates `people/workpersontwo_birch.md` with `origin: mentioned`, `status: stub`, and
   the reply says it started the file.
3. "tell me about Workpersontwo" resolves to that file (no "I didn't recognise").
4. With the fake web enabled, a `web` step saves `sources/web/<id>.json` and the answer's
   sources list includes a `Web:` label.
5. "no" instead of "yes" writes `state/people_declined.yaml`, and the same question asked
   again makes no offer.

### 6.2 Support

- `tests/support/heuristic_llm.py`: `answer_check`, `dig_step` (scripted per test) and
  `web_links`.
- `tests/support/fake_web.py`: canned links and pages; tests never touch the network
  (the fetcher takes an injectable client).

### 6.3 Unit tests

- `dead_end` set by each listed intent path; not set for correct empty results.
- `brief` with only unknown names shows "I don't know anyone called X." (Vignette V gap).
- Answer check skip rules (each in §1.2).
- Dig: round cap, `max_usd` cap, refused repeats, refused `open` outside the allowed set,
  unknown `do`, `LLMError` mid-loop, empty result keeps the first answer plus the
  "looked further" line.
- Web: refused queries (§3.3), size/type/timeout limits, 7-day reuse, short pages skipped,
  saved file indexed with the `Web:` label.
- Offer: 2-source minimum, declined names, the user, role accounts, `(via …)` names,
  fullest form chosen, yes/no matching, email alias picked up from a header.
- Evidence for mentioned people: full name matches, a bare first name doesn't.

### 6.4 Prompt eval

`scripts/prompt_eval.py` gains `answer_check` cases, including both real Workpersontwo asks
("no meetings" → unhelpful; the `who` answer → helpful) and correct empty results
("nothing open" → helpful).

## 7. Docs and bundle

- `docs/DESIGN.md`:
  - §2.3: `sources/web/` is written by the dig loop's web action, not a connector cycle.
  - §2.8: the only outside reads are the model call, connectors, and the web action.
  - §4.2: "Mentioned people" paragraph; `origin` as an Archie-owned key.
  - §8: two new steps between Verify and Render (check, then dig when needed), and the
    offer to start a file.
  - §9: still no tools; code runs the dig loop; `web_links` is the one grounded call and
    returns only URLs.
- `docs/VIGNETTES.md`: vignette W and its Coverage row.
- OKF: new `okf/components/dig.md` (`status: active` once code lands); updates to
  `ask.md`, `llm.md`, `connectors.md`, `derivers.md`, `index-search.md`; dated entry in
  `okf/log.md`.
- graphify update after doc changes.

## 8. Build order

Each step leaves the suite green.

1. `brief` keeps `said` for unknown names; `dead_end` on `Answer` and the intents.
2. The answer check and the handoff plumbing (dig stubbed to "nothing more").
3. The dig loop with local actions; progress lines in TUI and CLI.
4. The web action: `web_links`, fetcher, `sources/web/`, indexing.
5. The offer, yes/no handling, `start_person`, mentioned-people evidence.
6. Vignette W, docs, OKF, graphify.

## As built (2026-10-05)

Where the code differs from the text above:

- **The packet stops adding when full.** When a step's excerpts don't fit within
  `ask.max_sources` / `ask.max_source_chars`, the rest are left out and the notebook says
  "Some results didn't fit"; nothing already in the packet is evicted.
- **The offer runs after any question answer**, dug or not, whenever the dig switch is on.
  So "Tell me about Workpersontwo" also offers, when two source files name her.
- **The offer's name** is the longest form that two different files use ("Workpersontwo
  Petrova"), so a word that once happened to follow the name isn't taken for a surname.
- **The yes is saved in `journal/told.md`** as `"yes" → Started a file on Workpersontwo Birch
  …`, not `remembered: …`, so the replay of person tellings never re-runs it.
- **The facts pass** for the new file is `enrich.enrich_person`, which wraps `_enrich_one`
  (`fresh=True`) and records the person in `state/people_enriched.yaml`.
- **Mentioned-people evidence** lives in `ask/evidence.person_chunks` (used by
  `person_evidence` and `who`'s "Recent" list) on top of `Index.chunks_naming`, rather
  than in `PeopleDirectory.identifiers`, which still returns only addresses and handles.
  `PeopleDirectory.mention_names` gives the multi-word names. A person's own dossier is
  never counted as a mention, and the briefing's "last talked" still uses mail only.
- **Start a file** without an offer (`start_person`) searches the index for the name
  (one word allowed there, since the user asked for it by name) and needs one source. A
  pronoun is refused as a name.
- **A reply to the offer that isn't a plain yes or no** still drops it, but the
  understanding call is shown the offer, so "yes, start one for her" becomes `start_person`
  on the offered name.
- **Web pages stay out of people's evidence and the offer's count.** `sources/web/` pages
  never count as a person's evidence (a namesake's page could become a dossier fact) or as
  one of "your sources". They reach the user only through a dig answer.
- **"I looked further" is said only when a step ran.** If every step was refused or the
  first model call failed, the first answer stands with no added line.
- **The web step is refused** when what's left of `max_usd` can't cover the search fee and
  the answer.
- **Redirects are followed by code**, each hop checked: https, a public address, at most 5
  hops, and 10 s for the whole fetch.

## Out of scope

- Digging for tellings or instructions (they're acted on, not answered).
- Creating files for organisations or projects from mentions.
- Background digging after sync; digging happens only when the user asks.
- A "try harder" pushback command (the check and dead ends cover it for now).

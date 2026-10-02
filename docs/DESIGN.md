# Archie — Design

> **Status:** source of truth for how Archie is built. If code and this doc disagree,
> either fix the code or change this doc on purpose, never drift silently.
> The user-facing targets are in [VIGNETTES.md](VIGNETTES.md). Every feature exists to
> make one of those vignettes work.

## 1. What Archie is

Archie (from *archive*) is a single-user, local-first assistant for a software engineer
with real memory and face/name-recall difficulties. It mirrors the user's work sources
to local files, indexes them, and answers in plain English:

- **Before meetings:** who is in the meeting, what happened since the last one, and what's open.
- **Open loops:** questions asked of the user, promises the user made, and things the
  user is waiting on, tracked until they're closed.
- **Focus:** "what should I work on next?"
- **Long-term record:** what the user did, with whom, and when, so a year from now a
  performance review writes itself.

The user talks to Archie through **one entry point, `archie ask`**, typed in the TUI or
from a shell.

## 2. Principles (non-negotiable)

1. **Files are the source of truth.** Everything Archie knows lives in human-readable
   files under `~/.archie/`: raw source mirrors (JSON) and derived notes (Markdown with
   YAML frontmatter). The folder can be committed to git and moved between machines.
2. **SQLite is a disposable index.** `archie.db` holds only FTS5 and sqlite-vec indexes
   plus bookkeeping for the indexer. Deleting it loses nothing, and `archie admin
   reindex` rebuilds it from files. No fact may exist only in SQLite.
3. **Raw and derived files are separate.** Connectors write only `sources/`. Everything
   else (people, meetings, loops, briefings) is derived and may be edited by the user.
4. **The fence rule.** In derived files the user edits, Archie writes only inside
   `<!-- archie:auto -->` … `<!-- /archie:auto -->` fences. Archie may rewrite a fence's
   contents but never touches text outside a fence. Frontmatter keys Archie owns are listed
   per file type (§4). The user may also edit those keys, and the user's value wins.
5. **The LLM extracts and writes. Code verifies.** The LLM may classify, extract and
   summarize, but every factual claim it produces must carry a citation
   `{source_file, chunk_id, quote}`. Code checks that `quote` appears verbatim in the
   cited chunk, and **unverified claims are dropped, never shown**. Counts, dates, times
   and lists of items are computed by code, not by the LLM.
6. **Readable first.** Every answer opens with a short plain-English summary (2–4
   sentences). Details follow. Citations show as small `[n]` markers that expand on
   request. IDs, hashes and file paths never lead.
7. **Few commands.** `archie` opens the TUI, and `archie ask "..."` answers anything.
   Maintenance lives under `archie admin …`. A new capability is a new *intent* of
   `ask`, not a new command.
8. **Read-only toward the world.** Connectors only read (for example the
   `gmail.readonly` scope). Archie never sends, posts, comments or changes remote state.
9. **Keep everything.** Data is never pruned. The first sync of a source goes back
   only 2 weeks, and everything after that accumulates, so a year-long review becomes
   possible a year from now.

## 3. Architecture

```
            Remote sources (read-only)
  Calendar   Gmail   Drive   GitHub   Jira   (Slack: phase 2)
      │        │       │        │       │
      └────────┴───┬───┴────────┴───────┘
                   ▼  connectors: incremental, async, cursor-based
         ~/.archie/sources/<source>/…        (raw mirror, JSON, one file per object)
                   │
                   ▼  derivers (code + LLM extraction, verified)
   people/  meetings/  loops/  projects/      (derived Markdown, fenced)
                   │
                   ▼  indexer (hash-diffed, chunked)
            archie.db: FTS5 + sqlite-vec      (disposable)
                   │
                   ▼  ask router → intent → retrieval plan → context packet
              LLM synthesis → citation verifier → readable answer
                   │
                   ▼
            TUI (Textual) / `archie ask` CLI
```

### 3.1 Runtime

- **TUI-hosted.** The sync loop runs inside the TUI as asyncio tasks. The user keeps the
  TUI open in a window long-term. There is no launchd daemon.
- **Catch-up on launch.** On start, every connector syncs from its saved cursor before
  the regular cycle begins.
- **Cycle:** every 15 minutes (configurable per source). All connectors run in parallel
  (`asyncio.gather`). Each connector failure is isolated and logged, and never blocks the others.
- **CLI without the TUI.** `archie ask` from a shell reads the existing files and index
  and does not sync. It says how old the data is ("data as of 1:45 PM").
- **Single writer.** A lock file (`~/.archie/.lock`) stops two processes from syncing at
  once. A CLI `ask` only reads, so it doesn't need the lock.

## 4. Storage layout

```
~/.archie/
├── .gitignore               # archie.db*, logs/, .lock
├── config.yaml              # enabled sources, intervals, LLM backend, thresholds
├── me.yaml                  # the user's identities (see §4.1)
├── state/
│   └── cursors.yaml         # per-source sync cursors (tracked in git)
├── sources/                 # RAW: written only by connectors
│   ├── calendar/<eventId>.json
│   ├── gmail/<threadId>.json
│   ├── drive/<fileId>.json          # metadata + exported plain text
│   ├── github/<owner>__<repo>/pr-<n>.json, commits/<sha>.json
│   └── jira/<KEY-123>.json
├── people/<entity_id>.md    # dossiers
├── projects/<slug>.md       # project entities (repos, epics, docs, people)
├── meetings/<YYYY>/<YYYY-MM-DD>-<slug>.md   # one per meeting occurrence
├── briefings/<YYYY-MM-DD>/<HHMM>-<slug>.md  # generated briefings (kept as history)
├── loops/<YYYY>/<loop_id>.md
├── journal/weekly/<YYYY>-W<ww>.md           # weekly accomplishments
├── config/meeting_types.yaml               # user overrides: series → type
├── archie.db                # disposable index (ignored)
└── logs/                    # ignored
```

**Secrets** (OAuth tokens, API keys) live in the macOS Keychain through `keyring`, never
under `~/.archie/`, so the folder is always safe to commit.

**Times** are stored in UTC ISO-8601 and shown in local time.

**Deletions** in a source become a tombstone: the raw file gets `"deleted": true` and
`deleted_at`. The indexer drops the file's chunks. Derived notes that cite it keep the
citation, which is marked "source deleted".

### 4.1 `me.yaml`

```yaml
name: "Test Testerson"                 # what Archie calls the user
legal_name: "Harold Test Testerson III"
aliases: ["Test", "Test Testerson", "Harold Testerson", "Harold Test Testerson III", "H. Test Testerson"]
emails: ["test.testerson@example.com"]   # add work addresses here
github: null              # set when the GitHub connector is added
jira_account_id: null
slack_id: null            # phase 2
timezone: "America/Los_Angeles"
```

Everything that asks "is this me?" uses this file and nothing else. `aliases` covers
mentions by name ("Test, can you…", "cc Harold Testerson"). Matching emails and handles is
exact. Name aliases match whole words only, so "Test" never matches "Jackson".

### 4.2 Dossier (`people/alex_rivera.md`)

```markdown
---
entity_id: alex_rivera
name: Alex Rivera
aliases: ["alex.r@company.com", "alexr", "Alex R."]   # Archie appends; user may edit
role: Senior Backend Engineer                         # user-owned once set
org: internal            # internal | external
status: active           # stub | active
first_seen: 2026-10-01T16:02:00Z
last_interaction: 2026-10-14T21:30:00Z
---

## My notes
Prefers code snippets over high-level summaries. Ask about their kid's soccer.

<!-- archie:auto -->
## What Archie knows
- Co-owns auth token expiry pipeline [1]
- Last 1:1 (Oct 14): agreed Alex drafts Redis fallback, I review by Oct 17 [2]

## Recent interactions
- Oct 14 — 1:1 (meetings/2026/2026-10-14-alex-1-1.md)
- Oct 12 — PR #412 "Fix redis connection pool drop" merged
<!-- /archie:auto -->

<!-- archie:citations
[1] sources/jira/ENG-102.json#c3 "I'll own the expiry pipeline with Priya"
[2] meetings/2026/2026-10-14-alex-1-1.md#c1 "I'll review the fallback by Thursday"
-->
```

**Entity resolution:** an exact match on email or handle aliases is deterministic. A
fuzzy name match ("Alex", "the backend lead") produces a *suggested* alias that the user
confirms through `ask`. Archie never silently merges two people.

**Unknown people:** a new email address in a meeting or thread creates a `status: stub`
dossier with `org` inferred from the email domain. A background job searches the index
for mentions and fills in the fenced section.

### 4.3 Meeting (`meetings/2026/2026-10-14-alex-1-1.md`)

```markdown
---
event_id: "abc123_20261014T210000Z"
series_id: "abc123"            # recurring series, if any
title: "Alex / Jay 1:1"
start: 2026-10-14T21:00:00Z
end: 2026-10-14T21:30:00Z
type: one_on_one               # resolved by §7.1
attendees: [alex_rivera, me]
linked_docs: [drive/1AbC…]     # attachments + user's private notes docs
---

## My notes
(pasted or typed by the user; free-form)

<!-- archie:auto -->
## Decisions
## Action items
- [me] Review Redis fallback logic — due 2026-10-17 [1]
- [alex_rivera] Draft fallback design [2]
<!-- /archie:auto -->
```

**Notes sources (detailed design deferred to the meeting-notes connector):**
- Google Docs attached to the calendar event.
- The user's private Google Docs of notes about a meeting. How a doc gets linked to a
  meeting (title convention, a link in the doc, or asking the user) is decided when that
  connector is built.
- Raw notes pasted through `ask` ("these are my notes from the 2pm design review: …"),
  which are written under `## My notes` of the matching meeting file.

Action items extracted from notes become loops (§6).

### 4.4 Project (`projects/auth-redesign.md`)

The frontmatter holds `aliases` (repo names, Jira epic keys, doc titles), `people`
and `status`. The fenced section holds a timeline of decisions and key changes. Projects
feed the handover vignette and narrow down searches.

## 5. Ingestion and indexing

### 5.1 Connectors

| Source   | Phase | Incremental mechanism                 | Raw unit             |
|----------|-------|---------------------------------------|----------------------|
| Calendar | 1     | `syncToken`                           | event (instance)     |
| Gmail    | 1     | `historyId` (falls back to a date query if expired, about 1 week) | thread |
| Drive    | 1     | `changes` page token                  | file (text export)   |
| GitHub   | 1     | `since` / `updated` sort              | PR, commit, review   |
| Jira     | 1     | JQL `updated >= cursor`               | issue (with comments)|
| Slack    | 2     | `conversations.history` `oldest`      | thread               |

Rules:
- **Backfill:** a newly connected source goes back **14 days**, then runs incrementally.
  Nothing is ever pruned.
- **Scope:** each connector fetches only what involves the user, as config allows (for
  example Jira issues where the user is assignee, reporter, watcher or mentioned, and
  GitHub repos listed in config).
- **One raw file per stable source ID.** An update overwrites the file. Writes are
  atomic (write to a temp file, then rename).
- **Cursors** are saved only after that batch's files are written.

### 5.2 Derivers

Derivers turn changed raw files into derived notes:
- **calendar → meetings:** creates or updates meeting files and resolves attendees to people.
- **gmail / jira / github → loops:** see §6.
- **any → people:** updates aliases, `last_interaction`, and the recent interactions list.
- **meeting notes → action items → loops.**

Derivers are idempotent: running one twice on the same input gives the same files.

### 5.3 Chunking

| Content           | Chunk unit                                              |
|-------------------|---------------------------------------------------------|
| Email             | one message, quoted reply text and signatures removed   |
| Docs / Markdown   | split at headings, about 300–400 tokens, 50-token overlap |
| Calendar event    | one chunk: title, time, attendees, description          |
| Jira issue        | description, then each comment as its own chunk         |
| GitHub            | PR body, each review comment, each commit message       |

Each chunk records `(file_path, chunk_id, char_start, char_end, source, ts, people[])`.
`chunk_id` is stable for a given file version (index-based plus a content hash).

### 5.4 Index (`archie.db`)

- `files(path PRIMARY KEY, sha256, indexed_at)`: the hash list that decides what to re-index.
- `chunks(chunk_id, path, char_start, char_end, source, ts, people_json)`
- `chunks_fts`: an FTS5 table over chunk text
- `chunks_vec`: a `vec0` table, `embedding FLOAT[384]`
- `meta(key, value)`: `embed_model`, `chunker_version`, `schema_version`. A mismatch
  triggers a full reindex.

**Embeddings:** `BAAI/bge-small-en-v1.5` (384 dims, 512-token input) through
`sentence-transformers`, run locally.

**Hybrid search:** take the FTS5 top-k and the vector top-k, then merge them with
Reciprocal Rank Fusion (k=60). Results can be filtered by `source`, a time window, and
`people`.

## 6. Open loops

A loop is something that needs closing and involves the user.

### 6.1 Kinds

| Kind          | Meaning                                    | Typical evidence                    |
|---------------|--------------------------------------------|-------------------------------------|
| `asked_of_me` | someone asked the user a question or for something | inbound email, Jira mention, PR review request |
| `i_promised`  | the user committed to something            | the user's sent mail ("I'll send it Friday"), meeting action items |
| `waiting_on`  | the user asked someone, and no answer yet  | the user's sent mail with a question, the user's review request |

### 6.2 Detection

1. **Code pre-filter:** keep only messages that involve the user (per `me.yaml`).
   Skip automated mail (a `List-Unsubscribe` header, noreply senders, rules in
   `config.yaml`). Being in To ranks above being in Cc.
2. **LLM extraction:** a cheap model reads each new message and returns candidate loops
   `{kind, counterpart, summary, due?, quote}`.
3. **Verify:** `quote` must appear verbatim in the message, or the candidate is dropped.
4. **Dedup:** a candidate that matches an open loop (same counterpart and high vector
   similarity on the summary) adds a source to that loop instead of creating a new one.
5. **Due dates:** an explicit date in the quote is parsed by code. Otherwise there is no due date.

### 6.3 Closure: evidence or the user, never silent

- **Same thread:** the user replies after an `asked_of_me` message, or the counterpart
  replies after a `waiting_on` message. The LLM checks whether the reply addresses the
  quote, returning `{addresses: bool, quote}`, which is verified. If it does, the loop
  closes with `closed_by` pointing at the reply.
- **Other channels:** for each open loop, search the user's (or counterpart's) activity
  since the loop opened: a Jira transition, a submitted PR review, a meeting note. A
  strong verified match closes the loop. A weaker one marks it `maybe_done`, and Archie
  asks the user.
- **By the user through `ask`:** "done with Sarah's question", "snooze the Redis review
  till Monday", "that's not a loop".
- **Noise rules:** "that's not a loop" records a reason. A repeated pattern (same sender,
  same kind of mail) becomes an explicit rule in `config.yaml` that the user can see. It
  is never hidden learning.

### 6.4 File (`loops/2026/loop-20261001-0930-sarah-redis-review.md`)

```markdown
---
loop_id: loop-20261001-0930-sarah-redis-review
kind: asked_of_me
status: open              # open | snoozed | maybe_done | done | dismissed
counterpart: sarah_jones
summary: Review the Redis fallback patch on auth-v2
created_at: 2026-10-01T09:30:00Z
due: 2026-10-03
snoozed_until: null
sources:
  - {file: sources/gmail/18c2f.json, chunk: c0, quote: "can you review the Redis fallback patch before Friday?"}
closed_by: null           # {file, chunk, quote} or {user: "said done 2026-10-02"}
---

<!-- archie:auto -->
## History
- 2026-10-01 09:30 opened from email
<!-- /archie:auto -->
```

### 6.5 Ranking (used by `next` and briefings)

The score combines: due date is soon or past, age, counterpart importance (the user's
manager or people in an upcoming meeting score higher), kind (`asked_of_me` above
`waiting_on`), and whether the user is in To or Cc. The formula lives in code and its
weights in `config.yaml`, so ranking is explainable: each item can say *why* it ranks
where it does.

## 7. Briefings

### 7.1 Meeting type resolution (no LLM)

1. A user override in `config/meeting_types.yaml`, by `series_id` or exact title.
   Correcting one occurrence through `ask` writes an override for the whole series.
2. Title keywords: standup, daily or scrum means `standup`. All-hands, town hall or QBR
   means `all_hands`. Keywords come before structure, so a 2-person "Daily Standup" is
   still a standup.
3. Structure: 2 attendees (the user plus one) and recurring means `one_on_one`. 25 or
   more attendees means `all_hands`.
4. Otherwise `standard`.

### 7.2 Templates

| Type         | Retrieval plan (code)                                                   | Briefing focus |
|--------------|-------------------------------------------------------------------------|----------------|
| `one_on_one` | previous occurrence's meeting file, open loops with this person, their GitHub/Jira activity since then, the user's logged discussion topics | progress on commitments, changes since last time, topics to raise |
| `standup`    | the user's commits, PRs and Jira transitions since the last working day; In Progress issues; urgent `asked_of_me` loops | Yesterday / Today / Blockers |
| `all_hands`  | dossiers of leaders who are attending; recent org-wide docs and announcement mail | company-level context only; no peer detail |
| `standard`   | dossiers of all attendees; linked docs and their recent changes; hybrid search on title and description; open loops with attendees | who's who, state of play, what's open |

All templates add:
- **Unknown attendees:** "New: no history with Dana Kim (external, acme.com). Building a profile."
- **Conflicts:** the synthesis prompt asks for contradictions between sources. Each side
  must be cited and verified: "⚠️ Conflict: the email says the migration is paused [3],
  but Alex pushed 3 commits to auth-v2 yesterday [4]."

### 7.3 Timing

- **Morning batch:** on the first TUI launch or cycle of the day, build briefings for all
  of today's meetings.
- **T-15 refresh:** rebuild a briefing only if its context packet hash changed.
- **Notify:** a macOS notification at T-15 (`osascript`). The TUI's feed pane switches to
  the briefing.
- Each briefing shows "built 8:02, refreshed 1:45".

### 7.4 Output shape

```
2:00 PM · Design Review: Auth Redesign · 45 min

Alex and Priya want sign-off on moving session tokens to Redis. You owe Alex
a review of the fallback logic (due today), and Alex merged a related pool fix
yesterday.

People
  Alex Rivera — Senior Backend Eng. Last talked Oct 14 (1:1). Prefers code over prose.
  Priya Sharma — PM, auth. Last talked Sep 30 (planning).

Open with these people
  • You → Alex: review Redis fallback logic (due today) [1]

What changed
  • Auth_Migration_Draft edited by Alex 30m ago: adds Redis cluster section [2]
  • PR #412 "Fix redis connection pool drop" merged yesterday [3]

⚠️ Conflict: …
```

## 8. `archie ask`

`ask` is the only interface the user needs to remember. It's a pipeline:

1. **Route:** the LLM classifies the question into an intent and extracts parameters
   (people, time window, meeting, project). This is the one place the LLM output
   doesn't need a citation, because it selects a plan and states no facts.
2. **Retrieve:** the intent's plan runs in code (file reads plus index queries) and
   builds a **context packet** (JSON, each item with a citation key).
3. **Synthesize:** the LLM writes the answer from the packet only, with citations.
4. **Verify:** drop uncited or unverified claims. If nothing survives, say so plainly
   ("I couldn't find that").
5. **Render:** summary first, details next, then `[n]` citations that expand on request.

| Intent        | Example questions                                         | Vignette |
|---------------|-----------------------------------------------------------|----------|
| `brief`       | "prep me for 2pm", "what's my next meeting about?"        | A |
| `who`         | "who is Priya?", "what's my history with Alex?"           | B, J |
| `loops`       | "what do I owe people?", "what am I waiting on?"          | C |
| `loop_update` | "done with Sarah's question", "snooze that till Monday"   | C |
| `next`        | "what should I work on next?"                             | D |
| `ledger`      | "what did I accomplish this quarter?"                     | E, K |
| `search`      | "who touched the auth config last week?"                  | F |
| `handover`    | "write a handover for auth-redesign"                      | G |
| `notes`       | "notes from the design review: …"                         | H |
| `catchup`     | "what happened while I was out last week?"                | I |
| `correct`     | "that's a 1:1, not standup", "Alex R. is Alex Rivera"     | (all) |
| `help`        | "what can you do?", "how do I …?"                         | (all) |
| fallback      | anything else: hybrid search plus a cited answer          | — |

`archie admin` (not for daily use): `reindex`, `connect <source>`, `status`, `doctor`.

## 9. LLM interface

There is one module with one method:

```python
class Backend(Protocol):
    def complete(self, system: str, user: str, schema: dict, tier: str = "fast") -> dict: ...
```

`tier` is `fast` (routing, extraction) or `strong` (briefings, conflicts, handovers); config
maps each tier to a model.

- Text in, **JSON matching a schema** out. **No tools**, no file access and no network
  beyond the model call itself.
- **Backends:**
  - `claude-code` (default): the `claude -p` CLI in an empty temp directory with tools
    disabled, no MCP servers and no session persistence, using the user's Claude plan.
  - `anthropic` (not built yet): the SDK with an API key and structured outputs.
  - `fake`: replays canned responses, for tests.
- **Citations by reference number.** The model sees a numbered *context packet* of
  excerpts and cites `{ref, quote}`. Code maps `ref` back to `(file, chunk)` and checks the
  quote (whitespace, case and curly quotes are normalized, and quotes must be at least 8
  characters). The model never writes file paths, so it can't invent a source.
- **Prompts** live in `archie/llm/prompts/*.md` with `{placeholders}`, versioned in the repo.
- Calls run in parallel up to a configurable limit.

## 10. TUI

Built with Textual. Three panes:
1. **Feed:** the current or next briefing, top loops, and notifications.
2. **Ask:** an input box plus the answer view. Up-arrow recalls history. Citations
   expand inline.
3. **Activity:** sync status per source, the last sync time and recent errors.

The TUI owns the sync loop, morning batch, T-15 refresh and notifications.

## 11. Code layout

```
archie/
  cli.py                 # `archie`, `archie ask`, `archie admin …`
  config.py  me.py
  store/                 # file I/O, frontmatter, fences, atomic writes, tombstones
  connectors/            # calendar.py gmail.py drive.py github.py jira.py (+ base.py)
  derive/                # meetings.py people.py loops.py projects.py
  index/                 # chunk.py embed.py db.py search.py
  llm/                   # backend.py verify.py prompts/
  ask/                   # router.py intents/<intent>.py render.py
  briefings/             # classify.py templates/<type>.py build.py
  tui/
tests/
  unit/
  vignettes/             # one end-to-end test per vignette (see VIGNETTES.md)
  fixtures/              # fake raw sources for a fake week of work
```

**Stack:** Python 3.12+, `uv`, Textual, `sqlite-vec`, `sentence-transformers`,
`python-frontmatter`, `keyring`, `pytest`.

## 12. Testing strategy

- **Vignette tests are the acceptance bar.** `tests/fixtures/` holds a synthetic but
  realistic work history (calendar, threads, PRs, issues, docs). Each vignette has a test
  that runs the real pipeline (fake LLM backend, real index) and checks the facts in the
  output.
- **The verifier is tested adversarially:** fabricated quotes, quotes from the wrong
  chunk, and claims with no citation must all be dropped.
- **Rebuild test:** delete `archie.db`, reindex, and get the same search results.
- **Fence test:** a user edit outside fences survives every deriver run.

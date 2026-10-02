# `now` as an Archie source: design

**Status:** draft, waiting on the user's choice of auth (leaning toward option 1). No
code yet.
**Date:** 2026-10-02

## Goal

Treat the user's todo app `now` (`~/code/now`: FastAPI and Firestore on Cloud Run,
project `now-app-509021`) as part of their work. In priority order:

1. **One list of what's on their plate.** `now` todos join Archie's open items in
   "what's next?", the Today pane and standups, without duplicates when the same thing
   also exists as an email loop.
2. **Memory and context.** Todos, notes and links become searchable and citable, and
   briefings mention related todos.
3. **Record.** Completed todos count in "what did I get done" and the weekly brag doc.

## Constraints

- **Archie never writes to `now`** (DESIGN §2.8, read-only toward the world).
- **`now` must still cost nothing in GCP** (its #1 rule, `docs/okf/principles.md`).
  Archie's reads must stay at a few Firestore reads per sync.
- **Secrets live in the macOS Keychain** (`archie/secrets.py`), never in files.
- **Only the user's own list.** Shared lists and other family members' data are out of
  scope for v1 (assumption, to be confirmed).

## What `now` exposes (as of 2026-10-02)

- `GET /todos/rev` returns `{rev, revs, version, triggered_by}`. It is a cheap change
  check: one revision document.
- `GET /todos/tree` returns `{rev, revs, roots, todosById, ...}` with every item. It is
  cached server-side while `rev` is unchanged. **It is not side-effect-free:** it creates
  share mounts (`shares.ensure_mounts`) and can start calendar syncs
  (`_nudge_stale_calendars`).
- `GET /todos/next` returns the "Next up" ranking. It can also run the once-a-day archive
  sweep.
- **Item fields:** `todo_id`, `title`, `done`, `create_date`, `due_date` (midnight
  means all-day), `priority` (high/normal/low), `type` (todo, list, project, note,
  calendar, calendar_event, mount), `parent_id`/`child_ids`, `deleted`, `archived`,
  `repeat`, `content` (note body), `links`, `blocked_by`, `references`, `attachments`,
  `location`, `end_date`, `attendees`, `version`. Completion time is not stored, so it
  has to be inferred (see Record below).
- **Auth:** every request needs a Firebase ID token for an allowed Google account. The
  exceptions are a secret calendar-feed URL (`CALENDAR_TOKEN`) and OIDC for internal
  scheduler routes.

## Auth options

### 1. Read-only token on `now` (recommended)

This mirrors the existing `CALENDAR_TOKEN` pattern. The changes are in `now`:

- **New env var `ARCHIE_TOKEN`** (32+ random chars). If it's unset, the feature is off.
- **New route `GET /export/tree`.** It returns `{rev, items: [...]}` for the owner's own
  list only: no share splicing, no mount creation, no calendar nudge, no archive sweep.
  It reuses the same cached tree read `get_tree` uses. Archived and deleted items are
  included with their flags, so Archie can tell when something went away.
- **`GET /todos/rev` also accepts the token** (read-only).
- **In `require_user`:** a `Bearer <ARCHIE_TOKEN>` header, compared in constant time,
  unlocks only those two GET paths, as `owner()`. Any other path or method with that
  token returns 401.
- **Tests:** the token works only on those routes, `/export/tree` writes nothing (assert
  no mount, no task enqueued), a wrong token gets 401, and the feature is off when unset.
- **Deploy:** `ARCHIE_TOKEN=… ./deploy.sh` (or the Secret Manager pattern if `now` uses
  one). On the Archie side, `archie admin connect now --url https://… ` prompts for the
  token and stores it in the Keychain as `now-token`.

**Cost:** each Archie sync calls `/todos/rev` (one Firestore read). Only when `rev`
changed does it call `/export/tree`, which is served from the cache while `rev` is
unchanged, or one read per todo when the cache is cold. At 15-minute syncs that's about
96 rev reads a day plus a handful of tree reads, well inside the free tier.

### 2. Archie signs in like the web app

A one-time Google sign-in, after which Archie keeps a Firebase refresh token and mints
ID tokens. No `now` change. But the OAuth client must belong to `now`'s Firebase
project, the existing endpoints keep their side effects, and it's the most likely of the
three to break.

### 3. Read Firestore directly with `gcloud` credentials

No API and no deploy. But Archie would depend on `now`'s internal partition and document
layout and bypass its archive and share logic, so changes to `now` would break Archie
silently. Not recommended.

## Archie side (assuming option 1)

### Connector: `archie/connectors/now.py`

- **Config:** `connectors: {now: {enabled: true, url: https://<service>.run.app}}`. The
  token comes from the Keychain (`now-token`), read through `get_secret` so a Keychain
  prompt is explained instead of hanging.
- **Sync:**
  1. `GET /todos/rev`. If it equals the cursor's `rev`, nothing more to do.
  2. Otherwise `GET /export/tree`, then write one raw file per item to
     `sources/now/<todo_id>.json` (atomic, stable JSON).
  3. Items missing from the export that were mirrored before become tombstones.
- **Cursor:** `{rev, last_sync}`.
- **Normalized raw item:** the fields above, plus `path` (the titles of its ancestors,
  e.g. `Home › Kids › School`), `done_seen_at` (see Record) and `item_url` (a deep link
  into the web app if `now` supports one).
- **Chunker:** one chunk per item: title, path, due date, priority, notes (`content`)
  and link labels. The label is `Todo: <title> (<path>, due <date>)`, or `Note: …` for
  notes. People are attendee emails, for `calendar_event` items only.
- **Skipped:** `mount`, and `calendar`/`calendar_event` items (Archie already syncs
  Google Calendar directly; double-counting events would confuse the agenda).

### 1. One list: todos as open items

- **The Archie loop is a view of the todo, not a copy.** A new `derive/now_loops.py`
  maps open `todo`-type items with no open subtasks to loops with:
  - `kind: i_promised`, counterpart = the user (it's their own commitment)
  - `due` from `due_date`
  - priority high, which ranks like "due soon"
  - `sources` = the todo's chunk, and `thread: now:<todo_id>`

  These loops close when the todo is done, deleted or archived in `now`, never through
  Archie. `loop_update` on one of them says "Mark it done in now".
- **Dedupe with email loops:**
  - **Proposed check:** an open email loop and a `now` todo match when they share at
    least 3 content words, or when the todo's notes or links mention the email thread.
  - **When it fires:** the audit raises a `same_item` question ("Is 'Review Redis
    fallback' in now the same as Sarah's email ask?"). Yes links them, and the pair shows
    once in lists and closes together. No is remembered.
  - **Archie never merges these silently.**
- **Ranking:** `next` and the Today pane include `now` todos through the existing
  `rank()`. Today's agenda also gets a "Due today in now" line.

### 2. Memory and context

- `now` chunks are indexed like any source, so `search`, `who` (attendee or people
  mentions), `catchup` and `handover` can cite them.
- **Briefings:** hybrid search for the meeting title includes `now` items. A todo whose
  title or notes mention an attendee by name appears under "Open with these people".

### 3. Record

- **Completion time isn't stored by `now`.** The connector records `done_seen_at` the
  first time it sees `done: true` (a sync-granularity estimate, so within 15 minutes when
  the TUI is open).
- A new `activity` kind, `todo_done`, appears in the ledger as "Todos done", along with
  the weekly journal and standup "Yesterday".
- **Better (optional `now` change):** store `done_at` when an item is completed, and
  Archie prefers it when present.

## Testing

- **`now` side:** the auth and route tests listed under option 1.
- **Archie side:**
  - Connector tests against a fake `now`: rev unchanged means one call; rev changed means
    a full mirror plus tombstones; the token comes from the secrets layer.
  - A chunker test.
  - `now_loops` tests: open, then closed in `now`, means done; deleted means dismissed;
    `loop_update` refuses.
  - A `same_item` audit question test.
  - A `todo_done` activity test.
- **New vignette N ("My own list"):** the fixture week gets a `now` export. "What should
  I work on next?" mixes `now` todos with email asks, without duplicates, and "what did I
  get done" counts finished todos.

## Open questions

1. **Auth:** option 1, 2 or 3? (Leaning toward 1.)
2. **Shared lists:** include lists other family members share with you?
3. **Kinds:** should `note` items be loops? Proposed: no, notes are context only.
   Should `project` and `list` parents be loops? Proposed: no, only leaf todos.
4. **`done_at` in `now`:** worth adding for an exact record?

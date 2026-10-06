---
type: Component
title: Connectors
description: Read-only, incremental, cursor-based sync of remote sources into ~/.archie/sources/.
resource: archie/connectors/
status: active
tags: [component]
---

- `base.py`: the `Connector` protocol is `async sync(sctx, cursor) -> SyncResult(cursor, written, deleted)`. `SyncCtx` carries home, the connector's config section, me, now, backfill days and `say` (a progress sentence, callable from any thread).
- `registry.py`: `enabled_connectors(config)` returns the connectors switched on with `connectors: {name: {enabled: true}}`. Importing it also registers each connector's raw chunker.
- `google_auth.py`: read-only scopes for gmail, calendar and drive, plus `monitoring.read` for the Gemini usage check when `llm.google_project` is set. The token and client are stored in the Keychain via `keyring`. Connectors run in parallel and share one token, so refreshing it takes a lock (one refresh per expiry), and a failed Keychain save is logged and ignored: the refreshed token still works for this sync (a parallel save had failed calendar with "Can't store password on keychain"). `archie admin connect google [--client f] [--import-token f]` sets them up.
- `gmail.py`: writes one file per thread to `sources/gmail/<threadId>.json`.
  - Messages are normalized with from/to/cc, an ISO date, the plain-text body, and the flags `from_me`, `to_me`, `cc_me` and `bulk` (List-Unsubscribe header or a noreply sender).
  - Each sync after the first asks for mail `after:` the last sync, less an hour for late arrivals. A thread whose mirror already holds every listed message isn't fetched again. Gmail's history API isn't used: one day it reported 3,641 internal changes (no message added, deleted or relabelled) as touched threads, and refetching them used up the per-minute quota on every run. The cursor is `{last_sync}`; an older cursor that also has `history_id` still works.
  - Rate-limit waits (`google_retry.execute(req, say, "Gmail")`) and every 100 fetched threads are said through `sctx.say`, so a long backoff doesn't look like a hang.
  - By default it excludes Promotions, Social and chats.
  - The chunker makes one chunk per message, dropping quoted replies, and attaches the people (emails) and a label such as "Email from Sarah Jones: Subject (Oct 1)". `split_body` makes line endings the same first, so CRLF and LF mail strip alike (Workperson's CRLF signature had stayed in the message text). The signature below a `-- ` line becomes its own chunk `s{i}` labelled "Signature of Workperson Acorn (Sep 22)", with the sender as its only person, so titles in it can be quoted and read by code ([derivers](derivers.md) `titles.py`).

- `calendar.py`: syncs the primary calendar plus every calendar the user owns or can edit, such as a shared family calendar; read-only subscriptions like holidays are skipped. Writes one file per event instance to `sources/calendar/<id>.json`, prefixed with a short calendar hash for non-primary calendars, with recurring events expanded via `singleEvents`. The cursor is `{calendars: {id: syncToken}, utc: true, window_end}`, and the older single-token cursor still works. Only occurrences up to `lookahead_days` (60) ahead are kept: a token sync after a series edit returns every future copy, which had written 730 weekly "Swimming" copies out to 2040 (review 2026-10-05), so later ones are skipped. The window rolls: once `window_end` is a day or more behind `now + lookahead_days`, a dated list fetches the newly covered days, since unchanged copies never come through the token. The first sync with the new cursor removes stored copies past the window (they return as it rolls), and the meetings deriver removes their notes unless the user wrote in them. Event times are stored in UTC; the first sync without `utc` rewrites older files that kept Google's local offset (`to_utc`). Labels show local weekday and time.
  - The first sync covers the 14-day backfill plus `lookahead_days` (60) ahead. After that, `syncToken` returns only changes, and a 410 (expired token) triggers a full resync.
  - Cancelled events become tombstones.
  - Normalized fields: title, plain-text description, start/end, all_day, attendees (email, name, response, self, organizer; resources dropped), attachments (`file_id`, title, url, mime), conference link, link and `series_id`.
  - The chunker makes one chunk per event, labeled "Event: Title (Oct 14)".

- `drive.py`: writes Google Docs only, exported as plain text (capped at 200k characters), to `sources/drive/<fileId>.json`.
  - Which docs: ones the user owns or last modified, plus any doc attached to a calendar event (read from the local calendar mirror).
  - The first sync lists docs modified during the backfill window. After that, the changes feed (page token) returns only what changed, and removed or trashed docs become tombstones. Each sync also fetches attached docs that haven't been mirrored yet.
  - The chunker splits a doc into word windows labeled "Doc: Title (edited Oct 1)".

- `github.py`: read-only through the logged-in `gh` CLI (`gh api -X GET`). It uses search instead of a repo list, so it follows the user into any repo.
  - Queries: `involves:<user> updated:>=…` for PRs and issues (with their comments, plus reviews and merge state for PRs), `is:pr is:open review-requested:<user>` (flagged `review_requested_me`), and `author:<user>` for commits (with changed files).
  - Output: `sources/github/<owner>__<repo>/{pr,issue,commit}-<id>.json`. The cursor is `last_sync`, and each run re-queries from an hour before it.
  - The chunker makes one chunk per PR/issue body and per review or comment, plus one per commit. People appear as `gh:<login>`.
  - The live run found 102 items for `ttesterson1974`. Commit search returns at most 100 results per run.

- `jira.py`: Jira Cloud REST v3 search (GET only).
  - Which issues: updated since the cursor and assigned to, reported by, watched by, or commented on by the user.
  - Atlassian's document format is flattened to text with `@mentions` kept. Status transitions come from the changelog (`by_me`), and comments carry `mentions_me` and `from_me`.
  - Output: one file per issue at `sources/jira/<KEY>.json`. The chunker makes one chunk for the description and one per comment.
  - Auth: `archie admin connect jira --site … --email …` stores the API token in the Keychain. `me.yaml` needs `jira_account_id`.
  - Not yet tested against a live Jira site.

- `web.py`: public web pages for the dig loop's web step ([dig](dig.md)). It is not a connector cycle: it runs only when a question is being dug.
  - `web_search(ctx, query)`: `GeminiBackend.web_links` finds up to 3 links ([llm](llm.md)), and `fetch` saves each page to `sources/web/<sha1 of url>.json` (`url`, `title`, `fetched_at`, `query`, `text`). It indexes them (`Index.update_files`) and returns the chunks that best match the query.
  - Fetching: through `ctx.web` (an injectable `httpx.Client`; tests use `tests/support/fake_web.py`). Redirects are followed by code, up to 5 hops, and every hop must pass `public(url)`: https, not a local name (`localhost`, `.local`, `.lan`, …), and, on a real connection, a name that resolves only to public addresses. That keeps a page from sending the fetcher to the local network or over plain http. The final address is checked against what's already saved before downloading. Status 200, HTML or plain text only, at most 2 MB, 10 s for the whole fetch. Pages with under 200 characters of text (logins, consent walls) are skipped, and a page fetched in the last 7 days is reused.
  - `query_problem(q)` refuses a query with an `@`, a URL, a number of 5+ digits or more than 8 words, so nothing from the user's mail goes out.
  - The chunker labels page chunks "Web: Title (fetched Oct 5)", at most 4 per page.
- `pagetext.py`: HTML to text. `html_to_text` is Gmail's body conversion; `page_text` also drops head, nav, footer, svg, template and noscript for web pages; `html_title`.

All phase-1 connectors are built. Phase 2: Slack. Design: [DESIGN §5.1](../../docs/DESIGN.md#51-connectors). Principles: [read-only](../principles/read-only.md), [keep everything](../principles/keep-everything.md). Each cycle is run by [sync](sync.md).

---
type: Component
title: Connectors
description: Read-only, incremental, cursor-based sync of remote sources into ~/.archie/sources/.
resource: archie/connectors/
status: active
tags: [component]
---

- `base.py`: the `Connector` protocol is `async sync(sctx, cursor) -> SyncResult(cursor, written, deleted)`. `SyncCtx` carries home, the connector's config section, me, now and backfill days.
- `registry.py`: `enabled_connectors(config)` returns the connectors switched on with `connectors: {name: {enabled: true}}`. Importing it also registers each connector's raw chunker.
- `google_auth.py`: read-only scopes for gmail, calendar and drive. The token and client are stored in the Keychain via `keyring`. `archie admin connect google [--client f] [--import-token f]` sets them up.
- `gmail.py`: writes one file per thread to `sources/gmail/<threadId>.json`.
  - Messages are normalized with from/to/cc, an ISO date, the plain-text body, and the flags `from_me`, `to_me`, `cc_me` and `bulk` (List-Unsubscribe header or a noreply sender).
  - Incremental sync uses `historyId`. If that history has expired (404), it falls back to an `after:` date query from the last sync.
  - By default it excludes Promotions, Social and chats.
  - The chunker makes one chunk per message, dropping quoted replies and signatures, and attaches the people (emails) and a label such as "Email from Sarah Jones: Subject (Oct 1)".

- `calendar.py`: writes one file per event instance to `sources/calendar/<id>.json`, with recurring events expanded via `singleEvents`.
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

Phase 1 still to build: Jira. Phase 2: Slack. Design: [DESIGN §5.1](../../docs/DESIGN.md#51-connectors). Principles: [read-only](../principles/read-only.md), [keep everything](../principles/keep-everything.md). Each cycle is run by [sync](sync.md).

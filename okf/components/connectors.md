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

Phase 1 still to build: Calendar, Drive, GitHub, Jira. Phase 2: Slack. Design: [DESIGN §5.1](../../docs/DESIGN.md#51-connectors). Principles: [read-only](../principles/read-only.md), [keep everything](../principles/keep-everything.md). Each cycle is run by [sync](sync.md).

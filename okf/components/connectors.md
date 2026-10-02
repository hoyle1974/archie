---
type: Component
title: Connectors
description: Read-only, incremental, cursor-based sync of remote sources into ~/.archie/sources/.
resource: archie/connectors/
status: planned
tags: [component]
---

Phase 1: Calendar, Gmail, Drive, GitHub, Jira. Phase 2: Slack. One raw file per stable source ID, atomic writes, deletions become tombstones, and a new source backfills 14 days.

Writes only via [store](store.md). Feeds [derivers](derivers.md). Design: [DESIGN §5.1](../../docs/DESIGN.md#51-connectors). Principles: [read-only](../principles/read-only.md), [keep everything](../principles/keep-everything.md).

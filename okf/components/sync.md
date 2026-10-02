---
type: Component
title: Sync cycle
description: One cycle runs the enabled connectors in parallel, then the derivers on the files that changed, then the index.
resource: archie/sync.py
status: active
tags: [component]
---

`run_cycle(ctx, connectors, derivers)`:
- Each connector gets its saved cursor from `state/cursors.yaml`.
- Connectors run in parallel, except that one declaring `after = ("calendar",)` waits for a second wave because it reads that connector's mirror.
- Connector failures are isolated. A failed connector keeps its old cursor and its error is recorded in `state/sync_status.yaml`, while the others carry on.
- Derivers then receive every changed path.
- Finally `Index.sync()` runs in a worker thread.

The [TUI](tui.md) runs this every 15 minutes, plus once as a catch-up on launch. `archie admin sync` runs a single cycle. It runs [connectors](connectors.md), then [derivers](derivers.md), then [index-search](index-search.md).

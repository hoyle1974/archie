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
- Connectors run in parallel, ordered by `graphlib.TopologicalSorter`: one declaring `after = ("calendar",)` waits until calendar is done because it reads that connector's mirror. Chains of any depth work.
- Connector failures are isolated. A failed connector keeps its old cursor and its error is recorded in `state/sync_status.yaml`, while the others carry on.
- Derivers then receive every changed path. Each runs in a worker thread, because they call the model and the TUI must keep redrawing.
- Then `Index.sync()` runs in a worker thread, followed by `post_index` steps (people [enrichment](enrich.md)) and a second index sync.
- Last, when `llm.google_project` is set, Google's own Gemini token count is compared with Archie's log ([llm](llm.md) `google_usage.py`). A failed check is recorded and never stops the cycle.
- `on_progress` gets a plain sentence whenever what the cycle is waiting on changes: "Waiting on gmail, drive…" (shrinking as each source finishes), then "Reading what's new: loops…", "Updating the search index…", "Final checks…" and "Checking Google's token count…". The TUI shows it in the Sync pane; `archie admin sync` prints it to stderr.

The [TUI](tui.md) runs this every 15 minutes, plus once as a catch-up on launch. `archie admin sync` runs a single cycle. It runs [connectors](connectors.md), then [derivers](derivers.md), then [index-search](index-search.md).

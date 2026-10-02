---
type: Component
title: TUI
description: Textual app with Feed, Ask and Activity panes; hosts the asyncio sync loop, catch-up on launch, morning batch and notifications.
resource: archie/tui/
status: active
tags: [component]
---

Design: [DESIGN §3.1, §10](../../docs/DESIGN.md#10-tui). Runs [connectors](connectors.md), [derivers](derivers.md), [briefings](briefings.md).

- `app.py`: `ArchieApp(ctx, connectors, derivers, feed)`.
  - On mount it runs a catch-up `run_cycle`, then repeats it every `sync.interval_minutes`. ctrl+r syncs immediately.
  - Questions typed in the Ask input run `ask()` in a worker thread, and the answer is rendered with its sources.
  - `run_tui()` builds the real context.
- `feed.py`: `build_feed(ctx)` fills the Today pane. For now it only shows a placeholder until briefings and loops exist.

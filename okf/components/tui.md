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
  - On mount it runs a catch-up `run_cycle`, then repeats it every `sync.interval_minutes`. ctrl+r syncs immediately. Today is redrawn after every sync, after every answer, and every minute by the briefing tick, so finished meetings drop off right away.
  - Questions typed in the Ask input run `ask()` in a worker thread, and the answer is rendered with its sources. The Today pane refreshes after every answer, because answers can close loops, add notes or fix meetings.
  - The Ask pane's bottom border shows Gemini spend this month against the [budget](llm.md) (e.g. "Gemini: $0.02 of $15 this month"), polled every 3 seconds so calls from background sync and from `archie ask` in other terminals show up too. With `llm.google_project` set it adds Google's count (" · Google: $0.07"), marked "out of step" when the two are more than $1 apart; the Sync pane then shows the warning line and a toast pops up. The Sync pane scrolls (mouse wheel, or Tab to it and use the arrow keys), and Google's line comes right after "Last sync" so it's seen without scrolling. A model error such as a used-up budget is shown plainly, not as "Something went wrong".
  - `run_tui()` builds the real context.
- `feed.py`: `build_feed(ctx)` fills the Today pane with today's agenda (meetings and personal events, with times), then the next meeting's briefing. For now it only shows a placeholder until briefings and loops exist.
- Copying: drag to select and press Cmd+C or Ctrl+C, or press Ctrl+Y to copy the whole answer. `copy_to_clipboard` also calls `pbcopy`, because macOS Terminal ignores the OSC 52 escape that Textual uses.
- Single writer: the window that holds the [store](store.md) lock (`store/lock.py`) syncs and writes briefings. Any other window only answers questions.
- While a sync runs, the Sync pane shows what it's waiting on (see [sync](sync.md)), then the per-source results.
- Sync and ask failures write full tracebacks to `logs/errors.log`. While an answer is pending, the Ask pane shows "Still working… (Ns)" after 20 seconds and gives up after `ASK_TIMEOUT` (180s) with a message, so it can never stay stuck.
- Gotcha: sentence-transformers' tqdm builds a multiprocessing lock even with progress bars off. That spawn fails under Textual ("bad value(s) in fds_to_keep"), so `embed._thread_lock_for_tqdm()` installs a thread lock first.

---
type: Component
title: CLI
description: The `archie` command. Bare `archie` opens the TUI, `archie ask "…"` answers a question, and `archie admin …` runs maintenance.
resource: archie/cli.py
status: active
tags: [component]
---

`archie admin status` shows the index size and, for each enabled source, its last sync time or its current error.

A thin layer that dispatches to [ask](ask.md), [tui](tui.md) and the admin tasks. Following [one entry point](../principles/one-entry-point.md), any new capability becomes an ask intent, not a new subcommand.

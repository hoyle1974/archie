---
type: Component
title: CLI
description: The `archie` command. Bare `archie` opens the TUI, `archie ask "…"` answers a question, and `archie admin …` runs maintenance.
resource: archie/cli.py
status: active
tags: [component]
---

A thin layer that dispatches to [ask](ask.md), [tui](tui.md) and the admin tasks. Following [one entry point](../principles/one-entry-point.md), any new capability becomes an ask intent, not a new subcommand.

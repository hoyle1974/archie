---
type: Component
title: CLI
description: The `archie` command. Bare `archie` opens the TUI, `archie ask "…"` answers a question, and `archie admin …` runs maintenance.
resource: archie/cli.py
status: active
tags: [component]
---

`archie admin doctor` (`archie/doctor.py`) checks me.yaml, the Gemini API key, and each enabled source (Google scopes, `gh auth`, the Jira token), and prints a fix for anything that fails. `archie admin connect gemini` stores the Gemini API key in the Keychain. Keychain dialogs are reported rather than waited on. `archie admin status` shows the index size and, for each enabled source, its last sync time or its current error.

While `archie ask` digs further, each step is printed to stderr as it runs ("Looking further… searching “Workpersontwo Birch”"; see [dig](dig.md)), so stdout holds only the answer.

A thin layer that dispatches to [ask](ask.md), [tui](tui.md) and the admin tasks. Following [one entry point](../principles/one-entry-point.md), any new capability becomes an ask intent, not a new subcommand.

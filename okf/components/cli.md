---
type: Component
title: CLI
description: The `archie` command. Bare `archie` opens the TUI, `archie ask "…"` answers a question, and `archie admin …` runs maintenance.
resource: archie/cli.py
status: active
tags: [component]
---

`--gemma`/`--gemini` (`take_backend_flag`), works before or after the subcommand, picks the [LLM backend](llm.md) for that run; Gemma (local, via Ollama) is the default. It's threaded through every path that builds a `Ctx` (`archie`, `archie ask`, `archie admin sync/rederive`).

`archie admin doctor` (`archie/doctor.py`) checks me.yaml, the Gemini API key, and each enabled source (Google scopes, `gh auth`, the Jira token), and prints a fix for anything that fails. `archie admin connect gemini` stores the Gemini API key in the Keychain. `archie admin connect google` runs the OAuth flow and, once it gets scopes back, re-syncs immediately (inside the writer lock) so a connector that had just failed for lack of them retries right away. Keychain dialogs are reported rather than waited on. `archie admin status` shows the index size and, for each enabled source, its last sync time or its current error.

While `archie ask` digs further, each step is printed to stderr as it runs ("Looking further… searching “Workpersontwo Birch”"; see [dig](dig.md)), so stdout holds only the answer. It also prints which backend answered ("(answered by Gemma)") to stderr, so stdout stays just the answer.

A thin layer that dispatches to [ask](ask.md), [tui](tui.md) and the admin tasks. Following [one entry point](../principles/one-entry-point.md), any new capability becomes an ask intent, not a new subcommand.

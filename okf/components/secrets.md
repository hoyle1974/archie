---
type: Component
title: Secrets
description: Keychain access through keyring. A read that blocks on a macOS permission dialog fails after 15 seconds with an explanation instead of hanging.
resource: archie/secrets.py
status: active
tags: [component]
---

- `get_secret(key)` and `set_secret(key, value)` use the service name "archie". The keys are `google-token`, `google-client` and `jira-token`.
- macOS shows a permission dialog when a program it doesn't trust yet (for example the installed `archie` command, as opposed to the project venv that saved the token) reads an item. Until the user answers, the read blocks with no sign in the terminal. After 15 seconds `KeychainWaiting` says to look for the dialog and choose Always Allow. The [TUI](tui.md) Sync pane shows this as the source's error.

Used by [connectors](connectors.md) (Google auth, Jira) and the [CLI](cli.md) connect commands. Secrets never go in `~/.archie` or the repo.
